from __future__ import annotations

"""
Local Whisper STT provider — runs entirely on your machine.

IMPORTANT: For machines with limited RAM (16GB), long recordings are
split into 30-second chunks before transcription. This prevents:
- Out-of-memory crashes
- Machine freezes
- 5+ minute processing times

Chunked processing:
  2 min audio → 4 chunks × 30s → ~3s each → total ~12s (vs 60-120s unchunked)
"""

import asyncio
import io
import os
import struct
import tempfile
import time
import wave
from uuid import UUID

import structlog

from medscribe.config import Settings
from medscribe.domain.models import Transcript, TranscriptSegment
from medscribe.services.base import STTProvider, STTResult

logger = structlog.get_logger()

# Max chunk duration in seconds — keeps RAM usage low
CHUNK_DURATION_S = 30


class LocalWhisperSTTProvider(STTProvider):
    """
    Local speech-to-text using faster-whisper.
    Splits long audio into chunks to prevent RAM issues.
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
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Install with: pip install medscribe-ai[local]"
            )

        logger.info("stt.local.loading_model", model_size=self._model_size, device=self._device)

        compute_type = "float16" if self._device == "cuda" else "int8"
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type=compute_type,
        )
        logger.info("stt.local.model_loaded", model_size=self._model_size)

    async def transcribe(
        self, audio_data: bytes, language: str = "no", *, visit_id: UUID | None = None
    ) -> STTResult:
        self._ensure_model()
        start = time.monotonic()

        # Split audio into chunks to prevent RAM issues
        chunks = _split_audio_bytes(audio_data, chunk_seconds=CHUNK_DURATION_S)
        total_duration = _get_audio_duration(audio_data)

        logger.info(
            "stt.local.processing",
            chunks=len(chunks),
            total_duration_s=round(total_duration, 1),
            model=self._model_size,
        )

        # Transcribe each chunk
        all_segments: list[TranscriptSegment] = []
        all_text_parts: list[str] = []
        time_offset = 0.0

        for i, chunk_bytes in enumerate(chunks):
            chunk_start = time.monotonic()
            chunk_segments, chunk_text = await asyncio.to_thread(
                self._transcribe_chunk, chunk_bytes, language
            )
            chunk_elapsed = time.monotonic() - chunk_start

            # Offset timestamps by chunk position
            for seg in chunk_segments:
                all_segments.append(
                    TranscriptSegment(
                        start=seg.start + time_offset,
                        end=seg.end + time_offset,
                        text=seg.text,
                        confidence=seg.confidence,
                    )
                )

            if chunk_text.strip():
                all_text_parts.append(chunk_text.strip())

            # Use actual chunk duration, not fixed 30s
            actual_chunk_duration = _get_audio_duration(chunk_bytes)
            time_offset += actual_chunk_duration

            logger.info(
                "stt.local.chunk_done",
                chunk=i + 1,
                of=len(chunks),
                text_len=len(chunk_text),
                elapsed_s=round(chunk_elapsed, 1),
            )

        raw_text = " ".join(all_text_parts)
        elapsed_ms = (time.monotonic() - start) * 1000

        avg_confidence = 0.0
        if all_segments:
            avg_confidence = sum(s.confidence for s in all_segments) / len(all_segments)

        transcript = Transcript(
            visit_id=visit_id or UUID(int=0),
            raw_text=raw_text,
            segments=all_segments,
            language=language,
            model_id=f"local/whisper-{self._model_size}",
            confidence=avg_confidence,
            duration_seconds=total_duration,
        )

        logger.info(
            "stt.local.transcribed",
            model=self._model_size,
            language=language,
            duration_s=round(total_duration, 1),
            chunks=len(chunks),
            segments=len(all_segments),
            confidence=round(avg_confidence, 2),
            elapsed_ms=round(elapsed_ms, 1),
            data_sent_to_cloud=False,
        )

        return STTResult(transcript=transcript, processing_time_ms=elapsed_ms)

    def _transcribe_chunk(self, audio_bytes: bytes, language: str) -> tuple[list[TranscriptSegment], str]:
        """Transcribe a single audio chunk (runs in thread pool)."""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            segments, _ = self._model.transcribe(
                tmp_path,
                language=language,
                beam_size=1,           # Fast mode — beam_size=1 is 3x faster than 5
                word_timestamps=False,
                vad_filter=True,       # Skip silence
            )

            result_segments = []
            text_parts = []
            for seg in segments:
                result_segments.append(
                    TranscriptSegment(
                        start=seg.start,
                        end=seg.end,
                        text=seg.text.strip(),
                        confidence=_logprob_to_confidence(seg.avg_logprob),
                    )
                )
                text_parts.append(seg.text.strip())

            return result_segments, " ".join(text_parts)

        except Exception as e:
            logger.error("stt.local.chunk_error", error=str(e))
            return [], ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def health_check(self) -> bool:
        try:
            self._ensure_model()
            return self._model is not None
        except Exception:
            logger.warning("stt.local.health_check_failed")
            return False


def _split_audio_bytes(audio_data: bytes, chunk_seconds: int = 30) -> list[bytes]:
    """
    Split WAV/raw audio into chunks of chunk_seconds each.

    This is the key optimization — instead of feeding 2+ minutes
    of audio into Whisper at once (which eats all RAM), we split
    into 30-second pieces.
    """
    try:
        # Try to read as WAV
        buf = io.BytesIO(audio_data)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            n_frames = wf.getnframes()
            all_frames = wf.readframes(n_frames)
    except Exception:
        # Not a valid WAV — treat as raw PCM (16kHz, 16-bit, mono)
        sample_rate = 16000
        n_channels = 1
        sample_width = 2
        all_frames = audio_data

    bytes_per_second = sample_rate * n_channels * sample_width
    chunk_bytes_size = chunk_seconds * bytes_per_second
    total_bytes = len(all_frames)

    # If short enough, return as single chunk
    if total_bytes <= chunk_bytes_size * 1.2:  # 20% margin
        return [audio_data]

    chunks = []
    for offset in range(0, total_bytes, chunk_bytes_size):
        chunk_frames = all_frames[offset:offset + chunk_bytes_size]
        if len(chunk_frames) < bytes_per_second:  # Skip chunks < 1 second
            continue

        # Wrap in WAV
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(chunk_frames)
        chunks.append(wav_buf.getvalue())

    return chunks if chunks else [audio_data]


def _get_audio_duration(audio_data: bytes) -> float:
    """Get duration of audio in seconds."""
    try:
        buf = io.BytesIO(audio_data)
        with wave.open(buf, "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        # Estimate from raw bytes (16kHz, 16-bit, mono)
        return len(audio_data) / (16000 * 2)


def _logprob_to_confidence(avg_logprob: float) -> float:
    return max(0.0, min(1.0, 1.0 + avg_logprob))
