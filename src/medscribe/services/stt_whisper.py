from __future__ import annotations

"""
Whisper STT provider — using OpenAI's Whisper API.

For production, you'd want to also support:
- Local Whisper (faster-whisper) for privacy
- Azure Speech Services for enterprise
- Google Cloud Speech-to-Text

But the interface stays the same — that's the point.
"""

import time
from io import BytesIO
from uuid import UUID

import structlog
from openai import AsyncOpenAI

from medscribe.config import Settings
from medscribe.domain.models import Transcript, TranscriptSegment
from medscribe.services.base import STTProvider, STTResult

logger = structlog.get_logger()


class WhisperSTTProvider(STTProvider):
    """OpenAI Whisper API for speech-to-text."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
        )
        self._model = "whisper-1"

    async def transcribe(
        self, audio_data: bytes, language: str = "no", *, visit_id: UUID | None = None
    ) -> STTResult:
        start = time.monotonic()

        # Whisper API expects a file-like object
        audio_file = BytesIO(audio_data)
        audio_file.name = "audio.wav"

        response = await self._client.audio.transcriptions.create(
            model=self._model,
            file=audio_file,
            language=language,
            response_format="verbose_json",  # Get timestamps + segments
            timestamp_granularities=["segment"],
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        # Map Whisper segments to our domain segments
        segments = []
        if hasattr(response, "segments") and response.segments:
            for seg in response.segments:
                segments.append(
                    TranscriptSegment(
                        start=seg.get("start", 0.0) if isinstance(seg, dict) else seg.start,
                        end=seg.get("end", 0.0) if isinstance(seg, dict) else seg.end,
                        text=seg.get("text", "") if isinstance(seg, dict) else seg.text,
                        confidence=seg.get("avg_logprob", 0.0)
                        if isinstance(seg, dict)
                        else getattr(seg, "avg_logprob", 0.0),
                    )
                )

        transcript = Transcript(
            visit_id=visit_id or UUID(int=0),
            raw_text=response.text,
            segments=segments,
            language=language,
            model_id=f"openai/{self._model}",
            duration_seconds=getattr(response, "duration", 0.0) or 0.0,
        )

        logger.info(
            "stt.whisper.transcribed",
            language=language,
            duration_s=transcript.duration_seconds,
            segments=len(segments),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return STTResult(transcript=transcript, processing_time_ms=elapsed_ms)

    async def health_check(self) -> bool:
        try:
            await self._client.models.retrieve("whisper-1")
            return True
        except Exception:
            logger.warning("stt.whisper.health_check_failed")
            return False
