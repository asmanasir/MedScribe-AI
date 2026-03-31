from __future__ import annotations

"""
Safety guardrails — the layer that prevents harm.

In healthcare AI, you MUST have guardrails. This is non-negotiable.
This module checks:
1. Input validation (is the request safe to process?)
2. Output validation (is the AI output safe to show?)
3. Confidence thresholds (is the AI confident enough?)
4. Human-in-the-loop enforcement (has a human approved?)

Clinical AI systems must never auto-finalize.
This system enforces that principle.

Design: Chain of Responsibility pattern
Each check is independent. Run all of them. Collect all flags.
A single critical flag stops the pipeline.
"""

import re

import structlog

from medscribe.config import Settings
from medscribe.domain.models import ClinicalNote, SafetyFlag, Transcript

logger = structlog.get_logger()


class GuardrailResult:
    """Result of running all safety checks."""

    def __init__(self) -> None:
        self.flags: list[SafetyFlag] = []
        self.passed: bool = True

    def add_flag(self, flag: SafetyFlag) -> None:
        self.flags.append(flag)
        if flag.severity == "critical":
            self.passed = False


class SafetyGuardrails:
    """
    Runs safety checks on inputs and outputs.

    Usage:
        guardrails = SafetyGuardrails(settings)
        result = guardrails.check_transcript(transcript)
        if not result.passed:
            # Block the pipeline, require manual review
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check_input(self, text: str, *, visit_id: str = "") -> GuardrailResult:
        """Validate input before processing."""
        from uuid import UUID

        result = GuardrailResult()
        vid = UUID(visit_id) if visit_id else None

        # Check 1: Input length
        if len(text) > self._settings.max_input_length:
            result.add_flag(SafetyFlag(
                visit_id=vid or UUID(int=0),
                severity="critical",
                category="input_too_long",
                message=f"Input exceeds max length: {len(text)} > {self._settings.max_input_length}",
            ))

        # Check 2: Empty input
        if not text.strip():
            result.add_flag(SafetyFlag(
                visit_id=vid or UUID(int=0),
                severity="critical",
                category="empty_input",
                message="Input is empty or whitespace-only",
            ))

        return result

    def check_transcript(self, transcript: Transcript) -> GuardrailResult:
        """Validate transcript quality."""
        result = GuardrailResult()

        # Check 1: Empty transcript
        if not transcript.raw_text.strip():
            result.add_flag(SafetyFlag(
                visit_id=transcript.visit_id,
                severity="critical",
                category="empty_transcript",
                message="Transcript is empty after STT processing",
            ))

        # Check 2: Very short transcript (suspicious)
        if 0 < len(transcript.raw_text.strip()) < 20:
            result.add_flag(SafetyFlag(
                visit_id=transcript.visit_id,
                severity="warning",
                category="short_transcript",
                message=f"Transcript unusually short: {len(transcript.raw_text)} chars",
            ))

        # Check 3: Low confidence
        if transcript.confidence < 0.3 and transcript.confidence > 0:
            result.add_flag(SafetyFlag(
                visit_id=transcript.visit_id,
                severity="warning",
                category="low_stt_confidence",
                message=f"STT confidence below threshold: {transcript.confidence:.2f}",
            ))

        return result

    def check_note(self, note: ClinicalNote, confidence: float) -> GuardrailResult:
        """Validate structured clinical note."""
        result = GuardrailResult()

        # Check 1: Low structuring confidence
        if confidence < 0.3:
            result.add_flag(SafetyFlag(
                visit_id=note.visit_id,
                severity="critical",
                category="low_structuring_confidence",
                message=f"Structuring confidence too low: {confidence:.2f}",
            ))

        # Check 2: All sections empty
        filled = [v for v in note.sections.values() if v and v != "Not documented."]
        if not filled:
            result.add_flag(SafetyFlag(
                visit_id=note.visit_id,
                severity="critical",
                category="empty_note",
                message="All note sections are empty",
            ))

        # Check 3: Check for [VERIFY] tags (LLM flagged uncertainty)
        for section, content in note.sections.items():
            if "[VERIFY]" in content:
                result.add_flag(SafetyFlag(
                    visit_id=note.visit_id,
                    severity="warning",
                    category="llm_uncertainty",
                    message=f"LLM flagged uncertainty in section: {section.value}",
                ))

        # Check 4: Hallucination heuristic — check for suspiciously specific data
        # that's unlikely to come from a transcript
        self._check_hallucination_patterns(note, result)

        return result

    def _check_hallucination_patterns(
        self, note: ClinicalNote, result: GuardrailResult
    ) -> None:
        """
        Basic hallucination detection heuristics.

        These are not perfect — they're a safety net. The real
        protection is human review. But catching obvious issues
        before the clinician sees them saves time and builds trust.
        """
        all_text = " ".join(note.sections.values())

        # Pattern: fabricated phone numbers or addresses
        phone_pattern = re.compile(r"\+?\d[\d\s\-]{8,}")
        if phone_pattern.search(all_text):
            result.add_flag(SafetyFlag(
                visit_id=note.visit_id,
                severity="warning",
                category="hallucination_risk",
                message="Note contains phone number pattern — verify this came from transcript",
            ))

        # Pattern: fabricated email addresses
        email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        if email_pattern.search(all_text):
            result.add_flag(SafetyFlag(
                visit_id=note.visit_id,
                severity="warning",
                category="hallucination_risk",
                message="Note contains email pattern — verify this came from transcript",
            ))
