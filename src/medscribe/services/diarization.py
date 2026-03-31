from __future__ import annotations

"""
Speaker Diarization — identifies WHO spoke WHEN in clinical audio.

In a clinical consultation, there are typically 2-3 speakers:
  - Doctor (Lege)
  - Patient (Pasient)
  - Sometimes: Nurse, Family member, Interpreter

This module separates speakers so the LLM knows:
  - What the PATIENT reported (symptoms, history)
  - What the DOCTOR observed (findings, assessment)
  - What was discussed (plan, medications)

How it works:
1. Audio goes through speaker diarization (pyannote.audio)
2. Each segment gets a speaker label (SPEAKER_00, SPEAKER_01, etc.)
3. We combine diarization with Whisper transcription
4. Result: timestamped text with speaker labels

The LLM then structures the note correctly — patient's words go to
"Chief Complaint" and "History", doctor's findings go to "Examination".

Two modes:
  SIMPLE — No diarization, single speaker (current default)
  DIARIZED — Speaker separation using pyannote (when enabled)
"""

import asyncio
import os
import tempfile
from dataclasses import dataclass

import structlog

logger = structlog.get_logger()


@dataclass
class DiarizedSegment:
    """A segment of audio with speaker identification."""
    speaker: str        # "SPEAKER_00", "SPEAKER_01", etc.
    speaker_label: str  # "Lege", "Pasient" (assigned after mapping)
    start: float        # Start time in seconds
    end: float          # End time in seconds
    text: str           # Transcribed text for this segment


@dataclass
class DiarizedTranscript:
    """Complete transcript with speaker separation."""
    segments: list[DiarizedSegment]
    speaker_count: int
    speaker_map: dict[str, str]  # {"SPEAKER_00": "Lege", "SPEAKER_01": "Pasient"}

    @property
    def full_text(self) -> str:
        """Full transcript with speaker labels."""
        return "\n".join(
            f"[{seg.speaker_label}]: {seg.text}" for seg in self.segments if seg.text.strip()
        )

    @property
    def by_speaker(self) -> dict[str, str]:
        """Group all text by speaker."""
        result: dict[str, list[str]] = {}
        for seg in self.segments:
            if seg.text.strip():
                result.setdefault(seg.speaker_label, []).append(seg.text.strip())
        return {k: " ".join(v) for k, v in result.items()}


class SpeakerDiarizer:
    """
    Identifies different speakers in clinical audio.

    Uses pyannote.audio for speaker diarization. The model
    runs locally — no audio sent to cloud.

    Note: First run downloads the model (~300MB). Requires
    accepting pyannote's license on Hugging Face.
    """

    def __init__(self, num_speakers: int = 2) -> None:
        self._num_speakers = num_speakers
        self._pipeline = None

    def _ensure_pipeline(self):
        if self._pipeline is not None:
            return

        try:
            from pyannote.audio import Pipeline
            # Use the pre-trained speaker diarization pipeline
            # Note: requires HuggingFace token for first download
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=os.environ.get("HF_TOKEN"),
            )
            logger.info("diarization.model_loaded")
        except Exception as e:
            logger.warning("diarization.model_load_failed", error=str(e))
            self._pipeline = None

    async def diarize(
        self,
        audio_data: bytes,
        whisper_segments: list[dict] | None = None,
    ) -> DiarizedTranscript:
        """
        Run speaker diarization on audio data.

        Args:
            audio_data: WAV audio bytes
            whisper_segments: Pre-computed Whisper segments with text + timestamps

        Returns:
            DiarizedTranscript with speaker labels assigned to each segment
        """
        self._ensure_pipeline()

        if self._pipeline is None:
            # Fallback: no diarization, single speaker
            return self._fallback_single_speaker(whisper_segments or [])

        # Write to temp file for pyannote
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            # Run diarization in thread pool (CPU/GPU bound)
            diarization = await asyncio.to_thread(
                self._run_diarization, tmp_path
            )

            # Merge diarization with whisper segments
            segments = self._merge_segments(diarization, whisper_segments or [])

            # Auto-assign speaker labels (doctor = most speaking time usually)
            speaker_map = self._assign_speaker_labels(segments)

            for seg in segments:
                seg.speaker_label = speaker_map.get(seg.speaker, seg.speaker)

            return DiarizedTranscript(
                segments=segments,
                speaker_count=len(speaker_map),
                speaker_map=speaker_map,
            )

        except Exception as e:
            logger.error("diarization.failed", error=str(e))
            return self._fallback_single_speaker(whisper_segments or [])
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _run_diarization(self, audio_path: str):
        """Run pyannote diarization (synchronous, runs in thread)."""
        return self._pipeline(
            audio_path,
            num_speakers=self._num_speakers,
        )

    def _merge_segments(
        self,
        diarization,
        whisper_segments: list[dict],
    ) -> list[DiarizedSegment]:
        """
        Merge pyannote speaker labels with Whisper transcription.

        For each Whisper segment, find which speaker was talking
        at that time based on the diarization output.
        """
        segments = []

        for ws in whisper_segments:
            ws_start = ws.get("start", 0.0)
            ws_end = ws.get("end", 0.0)
            ws_text = ws.get("text", "")
            ws_mid = (ws_start + ws_end) / 2

            # Find the speaker at the midpoint of this segment
            speaker = "UNKNOWN"
            for turn, _, spk in diarization.itertracks(yield_label=True):
                if turn.start <= ws_mid <= turn.end:
                    speaker = spk
                    break

            segments.append(DiarizedSegment(
                speaker=speaker,
                speaker_label=speaker,  # Will be mapped later
                start=ws_start,
                end=ws_end,
                text=ws_text,
            ))

        return segments

    def _assign_speaker_labels(self, segments: list[DiarizedSegment]) -> dict[str, str]:
        """
        Assign human-readable labels to speakers.

        Heuristic: In a clinical consultation, the person who speaks
        more is usually the DOCTOR (asking questions, explaining).
        The person who speaks less is usually the PATIENT (answering).
        """
        # Count speaking time per speaker
        speaking_time: dict[str, float] = {}
        for seg in segments:
            duration = seg.end - seg.start
            speaking_time[seg.speaker] = speaking_time.get(seg.speaker, 0) + duration

        if not speaking_time:
            return {}

        # Sort by speaking time (most first)
        sorted_speakers = sorted(speaking_time.items(), key=lambda x: x[1], reverse=True)

        labels = ["Lege", "Pasient", "Annet"]
        speaker_map = {}
        for i, (speaker_id, _) in enumerate(sorted_speakers):
            speaker_map[speaker_id] = labels[i] if i < len(labels) else f"Taler {i + 1}"

        logger.info(
            "diarization.speakers_assigned",
            speakers=speaker_map,
            speaking_times={k: round(v, 1) for k, v in speaking_time.items()},
        )

        return speaker_map

    def _fallback_single_speaker(self, whisper_segments: list[dict]) -> DiarizedTranscript:
        """Fallback when diarization is unavailable."""
        segments = [
            DiarizedSegment(
                speaker="SPEAKER_00",
                speaker_label="Lege/Pasient",
                start=ws.get("start", 0.0),
                end=ws.get("end", 0.0),
                text=ws.get("text", ""),
            )
            for ws in whisper_segments
        ]
        return DiarizedTranscript(
            segments=segments,
            speaker_count=1,
            speaker_map={"SPEAKER_00": "Lege/Pasient"},
        )
