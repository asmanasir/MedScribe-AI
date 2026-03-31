from __future__ import annotations

"""
Clinical note structuring service.

This is where prompt engineering meets medicine. The structuring service
takes raw transcript text and produces a structured clinical note with
standard sections (complaint, history, examination, etc.).

Why is this separate from the LLM provider?
1. Prompt engineering is complex — it deserves its own module
2. You might use different models for structuring vs. general chat
3. Validation logic is structuring-specific
4. You might replace this with a fine-tuned model that doesn't need prompts

The prompts here are English-based but instruct the model to handle
Norwegian clinical language.
"""

import json
import time
from uuid import UUID

import structlog

from medscribe.domain.enums import NoteSection
from medscribe.domain.models import ClinicalNote
from medscribe.services.base import LLMProvider, StructuringResult, StructuringService

logger = structlog.get_logger()

# System prompt for clinical note structuring
STRUCTURING_SYSTEM_PROMPT = """You are a medical documentation assistant. Your role is to
structure clinical visit transcripts into organized clinical notes.

Rules:
1. Extract information ONLY from the provided transcript. Never invent or assume.
2. If a section has no relevant information, write "Not documented."
3. Use medical terminology appropriate for clinical records.
4. Maintain the original language of the transcript (Norwegian or English).
5. Be concise but complete — every clinically relevant detail matters.
6. Flag any content you are uncertain about with [VERIFY].

Output format: Return ONLY valid JSON with these exact keys:
- chief_complaint: The main reason for the visit
- history: Relevant medical history discussed
- examination: Physical examination findings
- assessment: Clinical assessment / diagnosis
- plan: Treatment plan and next steps
- medications: Any medications discussed (new, changed, or continued)
- follow_up: Follow-up instructions
"""

# Clinical Norwegian prompt — optimized for small local models (1B-3B)
STRUCTURING_SIMPLE_PROMPT = """Du er en norsk medisinsk dokumentasjonsassistent.
Skriv profesjonelt medisinsk norsk. Rett skrivefeil og bruk korrekt terminologi.

Konsultasjon:
{transcript}

Fyll ut feltene basert KUN på teksten over. Skriv kort og presist.
Bruk medisinsk norsk (ikke dagligtale). Skriv "Ikke dokumentert." hvis informasjon mangler.

{{"chief_complaint":"hovedgrunn for besøket", "history":"relevant sykehistorie", "examination":"funn ved undersøkelse", "assessment":"vurdering/diagnose", "plan":"behandlingsplan", "medications":"medisiner", "follow_up":"oppfølging"}}
JSON:"""

STRUCTURING_USER_PROMPT = """Structure the following clinical visit transcript into a clinical note.

{speaker_info}

Transcript:
{transcript}

Additional context:
{metadata}

{template_instructions}

Return ONLY the JSON object. No other text."""

# When transcript has speaker labels
SPEAKER_INFO_DIARIZED = """The transcript has speaker labels:
- [Lege] = Doctor's words (questions, findings, assessment)
- [Pasient] = Patient's words (symptoms, history, concerns)

Use the speaker labels to place information correctly:
- Patient's reported symptoms → Chief Complaint, History
- Doctor's observations → Examination, Assessment
- Agreed plan → Plan, Follow-up"""

SPEAKER_INFO_SINGLE = "This is a single-speaker transcript (no speaker separation)."


class LLMStructuringService(StructuringService):
    """
    Structures transcripts using an LLM provider.

    This service composes with an LLMProvider — it doesn't care
    whether the LLM is OpenAI or Ollama. That's dependency injection.
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def structure(
        self,
        transcript_text: str,
        visit_metadata: dict,
        *,
        visit_id: UUID | None = None,
        template_id: str | None = None,
    ) -> StructuringResult:
        start = time.monotonic()

        # Apply Norwegian STT corrections before structuring
        from medscribe.services.norwegian import apply_stt_corrections
        transcript_text = apply_stt_corrections(transcript_text)

        # Truncate to 500 chars — keeps LLM fast on CPU while preserving key info
        MAX_TRANSCRIPT_CHARS = 500
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            transcript_text = transcript_text[:MAX_TRANSCRIPT_CHARS]

        # Use SIMPLE prompt for small local models — much better results
        # The complex prompt with templates/speaker info is for large models (GPT-4, Llama 70B)
        prompt = STRUCTURING_SIMPLE_PROMPT.format(transcript=transcript_text)

        result = await self._llm.generate(
            prompt=prompt,
            system_prompt="Du er en norsk klinisk dokumentasjonsassistent. Skriv profesjonelt medisinsk norsk. Returner kun gyldig JSON.",
        )

        # Parse the LLM output into structured sections
        sections, confidence = self._parse_output(result.text)

        # Post-processing: fix terminology, remove repetitions, clean formatting
        from medscribe.services.post_processing import post_process_note
        sections = {k: v for k, v in post_process_note(
            {(k.value if hasattr(k, 'value') else str(k)): v for k, v in sections.items()}
        ).items()}
        # Re-map to NoteSection enums
        from medscribe.domain.enums import NoteSection
        sections = {NoteSection(k) if k in [e.value for e in NoteSection] else k: v for k, v in sections.items()}

        note = ClinicalNote(
            visit_id=visit_id or UUID(int=0),
            sections=sections,
            raw_llm_output=result.text,
            model_id=result.model_id,
        )

        elapsed_ms = (time.monotonic() - start) * 1000

        logger.info(
            "structuring.completed",
            model=result.model_id,
            sections_filled=len([v for v in sections.values() if v != "Not documented."]),
            confidence=round(confidence, 2),
            elapsed_ms=round(elapsed_ms, 1),
        )

        return StructuringResult(
            note=note,
            confidence=confidence,
            processing_time_ms=elapsed_ms,
        )

    def _parse_output(self, raw_output: str) -> tuple[dict[NoteSection, str], float]:
        """
        Parse LLM JSON output into typed sections.

        Returns (sections_dict, confidence_score).
        Confidence is based on: did we get valid JSON? Are sections filled?
        """
        # Try to extract JSON from the response
        text = raw_output.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("structuring.parse_failed", raw_output=raw_output[:200])
            return {section: "Not documented." for section in NoteSection}, 0.0

        # Map JSON keys to NoteSection enum
        section_map = {
            "chief_complaint": NoteSection.CHIEF_COMPLAINT,
            "history": NoteSection.HISTORY,
            "examination": NoteSection.EXAMINATION,
            "assessment": NoteSection.ASSESSMENT,
            "plan": NoteSection.PLAN,
            "medications": NoteSection.MEDICATIONS,
            "follow_up": NoteSection.FOLLOW_UP,
        }

        sections: dict[NoteSection, str] = {}
        filled = 0
        for key, section_enum in section_map.items():
            value = data.get(key, "Not documented.")
            # Small models sometimes return nested dicts instead of strings
            value = _flatten_value(value)
            sections[section_enum] = value
            if value and value != "Not documented.":
                filled += 1

        # Confidence: what fraction of sections were filled?
        confidence = filled / len(section_map) if section_map else 0.0

        return sections, confidence


def _flatten_value(value: object) -> str:
    """
    Flatten any LLM output value into a clean string.

    Small models (1B) often return nested structures like:
      {"chief_complaint": "X", "history_of_current_illness": "Y"}
    instead of a simple string. This extracts the meaningful text.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # Flatten list items
        parts = []
        for item in value:
            parts.append(f"- {_flatten_value(item)}")
        return "\n".join(parts)
    if isinstance(value, dict):
        # Extract all string values from nested dict, skip keys
        parts = []
        for k, v in value.items():
            flat = _flatten_value(v)
            if flat and flat != "Not documented.":
                parts.append(flat)
        return "\n".join(parts) if parts else "Not documented."
    return str(value) if value is not None else "Not documented."
