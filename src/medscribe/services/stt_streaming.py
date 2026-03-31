from __future__ import annotations

"""
Streaming speech-to-text — real-time transcription as the doctor speaks.

How it works:
1. Doctor speaks into mic → browser sends audio chunks via WebSocket
2. We buffer chunks into segments (every ~3 seconds of audio)
3. Each segment is transcribed with faster-whisper
4. Partial text is sent back immediately via WebSocket
5. Doctor sees text appearing in real-time

Why WebSocket (not REST)?
- REST = request → wait → response (batch mode)
- WebSocket = bidirectional stream (real-time)
- Doctor sees words appearing as they speak

Architecture:
  Browser (mic) --[WebSocket audio chunks]--> Server
  Browser <--[WebSocket text updates]-- Server (faster-whisper)
"""

import asyncio
import io
import tempfile
import os
import time
import wave
from collections.abc import AsyncGenerator

import structlog

from medscribe.config import Settings

logger = structlog.get_logger()


class StreamingTranscriber:
    """
    Buffers audio chunks and transcribes in near-real-time.

    The transcriber accumulates audio data and transcribes
    every `segment_duration` seconds, yielding partial results.
    """

    def __init__(self, settings: Settings) -> None:
        self._model_size = settings.whisper_model
        self._device = settings.whisper_device
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper not installed. pip install medscribe-ai[local]")

        compute_type = "float16" if self._device == "cuda" else "int8"
        self._model = WhisperModel(self._model_size, device=self._device, compute_type=compute_type)
        logger.info("streaming_stt.model_loaded", model=self._model_size)

    async def transcribe_stream(
        self,
        audio_queue: asyncio.Queue,
        language: str = "no",
        segment_duration: float = 3.0,
    ) -> AsyncGenerator[dict, None]:
        """
        Consume audio chunks from queue, yield transcription updates.

        Yields dicts:
          {"type": "partial", "text": "...", "is_final": False}
          {"type": "final", "text": "full transcript", "is_final": True}

        The caller puts audio bytes into audio_queue.
        Put None to signal end of stream.
        """
        self._ensure_model()

        buffer = bytearray()
        full_text_parts: list[str] = []
        sample_rate = 16000
        bytes_per_second = sample_rate * 2  # 16-bit mono
        segment_bytes = int(segment_duration * bytes_per_second)

        while True:
            try:
                chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                # Check if we have enough buffered audio to transcribe
                if len(buffer) >= segment_bytes:
                    text = await self._transcribe_buffer(bytes(buffer), language)
                    if text.strip():
                        full_text_parts.append(text.strip())
                        yield {
                            "type": "partial",
                            "text": " ".join(full_text_parts),
                            "segment": text.strip(),
                            "is_final": False,
                        }
                    buffer.clear()
                continue

            if chunk is None:
                # End of stream — transcribe remaining buffer
                if len(buffer) > bytes_per_second:  # At least 1 second
                    text = await self._transcribe_buffer(bytes(buffer), language)
                    if text.strip():
                        full_text_parts.append(text.strip())

                yield {
                    "type": "final",
                    "text": " ".join(full_text_parts),
                    "is_final": True,
                }
                break

            buffer.extend(chunk)

            # Transcribe when we have enough audio
            if len(buffer) >= segment_bytes:
                text = await self._transcribe_buffer(bytes(buffer), language)
                if text.strip():
                    full_text_parts.append(text.strip())
                    yield {
                        "type": "partial",
                        "text": " ".join(full_text_parts),
                        "segment": text.strip(),
                        "is_final": False,
                    }
                buffer.clear()

    async def _transcribe_buffer(self, audio_bytes: bytes, language: str) -> str:
        """Transcribe a buffer of raw PCM audio."""
        # Write to temp WAV file
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                with wave.open(tmp, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_bytes)

            # Run transcription in thread pool (CPU-bound)
            segments, _ = await asyncio.to_thread(
                self._model.transcribe,
                tmp_path,
                language=language,
                beam_size=1,  # Faster for streaming (less accurate but real-time)
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments)
            return text
        except Exception as e:
            logger.error("streaming_stt.transcribe_error", error=str(e))
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
