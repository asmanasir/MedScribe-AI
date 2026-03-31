"""
Tests for safety guardrails.

These tests verify that the guardrails catch dangerous conditions:
- Empty inputs
- Oversized inputs
- Low confidence scores
- Hallucination patterns
- Empty notes
"""

from uuid import uuid4

import pytest

from medscribe.config import Settings
from medscribe.domain.enums import NoteSection
from medscribe.domain.models import ClinicalNote, Transcript
from medscribe.safety.guardrails import SafetyGuardrails


@pytest.fixture
def guardrails():
    settings = Settings(max_input_length=1000)
    return SafetyGuardrails(settings)


@pytest.fixture
def visit_id():
    return uuid4()


# --- Input checks ---


def test_empty_input_is_critical(guardrails):
    result = guardrails.check_input("   ")
    assert not result.passed
    assert any(f.category == "empty_input" for f in result.flags)


def test_oversized_input_is_critical(guardrails):
    result = guardrails.check_input("x" * 2000)
    assert not result.passed
    assert any(f.category == "input_too_long" for f in result.flags)


def test_normal_input_passes(guardrails):
    result = guardrails.check_input("Patient reports headache for 3 days.")
    assert result.passed
    assert len(result.flags) == 0


# --- Transcript checks ---


def test_empty_transcript_is_critical(guardrails, visit_id):
    transcript = Transcript(visit_id=visit_id, raw_text="  ")
    result = guardrails.check_transcript(transcript)
    assert not result.passed


def test_short_transcript_warns(guardrails, visit_id):
    transcript = Transcript(visit_id=visit_id, raw_text="Hi")
    result = guardrails.check_transcript(transcript)
    assert result.passed  # Warning, not critical
    assert any(f.category == "short_transcript" for f in result.flags)


def test_low_confidence_warns(guardrails, visit_id):
    transcript = Transcript(visit_id=visit_id, raw_text="Normal text here", confidence=0.1)
    result = guardrails.check_transcript(transcript)
    assert any(f.category == "low_stt_confidence" for f in result.flags)


def test_good_transcript_passes(guardrails, visit_id):
    transcript = Transcript(
        visit_id=visit_id,
        raw_text="Patient reports headache for 3 days. No fever.",
        confidence=0.95,
    )
    result = guardrails.check_transcript(transcript)
    assert result.passed
    assert len(result.flags) == 0


# --- Note checks ---


def test_empty_note_is_critical(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={s: "Not documented." for s in NoteSection},
    )
    result = guardrails.check_note(note, confidence=0.5)
    assert not result.passed


def test_low_confidence_note_is_critical(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={NoteSection.CHIEF_COMPLAINT: "Headache"},
    )
    result = guardrails.check_note(note, confidence=0.1)
    assert not result.passed
    assert any(f.category == "low_structuring_confidence" for f in result.flags)


def test_verify_tag_warns(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={NoteSection.MEDICATIONS: "Paracetamol 500mg [VERIFY]"},
    )
    result = guardrails.check_note(note, confidence=0.8)
    assert any(f.category == "llm_uncertainty" for f in result.flags)


def test_hallucination_phone_warns(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={NoteSection.PLAN: "Call patient at +47 123 456 789"},
    )
    result = guardrails.check_note(note, confidence=0.8)
    assert any(f.category == "hallucination_risk" for f in result.flags)


def test_hallucination_email_warns(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={NoteSection.FOLLOW_UP: "Send results to patient@hospital.no"},
    )
    result = guardrails.check_note(note, confidence=0.8)
    assert any(f.category == "hallucination_risk" for f in result.flags)


def test_good_note_passes(guardrails, visit_id):
    note = ClinicalNote(
        visit_id=visit_id,
        sections={
            NoteSection.CHIEF_COMPLAINT: "Hodepine i 3 dager",
            NoteSection.ASSESSMENT: "Tensjonshodepine",
            NoteSection.PLAN: "Paracetamol ved behov. Kontroll om 2 uker.",
        },
    )
    result = guardrails.check_note(note, confidence=0.85)
    assert result.passed
