"""
Tests for domain models — ensure business objects behave correctly.

These tests verify:
- Default values are set correctly
- UUIDs are generated uniquely
- Timestamps are UTC
- Enums serialize to strings
"""

from datetime import timezone

from medscribe.domain.enums import NoteSection, VisitStatus
from medscribe.domain.models import (
    AuditEntry,
    ClinicalNote,
    SafetyFlag,
    Transcript,
    Visit,
)


def test_visit_defaults():
    visit = Visit(patient_id="P001", clinician_id="DR001")
    assert visit.status == VisitStatus.CREATED
    assert visit.created_at.tzinfo == timezone.utc
    assert visit.metadata == {}


def test_visit_uuid_uniqueness():
    v1 = Visit(patient_id="P001", clinician_id="DR001")
    v2 = Visit(patient_id="P001", clinician_id="DR001")
    assert v1.id != v2.id


def test_transcript_segments():
    from medscribe.domain.models import TranscriptSegment

    seg = TranscriptSegment(start=0.0, end=1.5, text="Hello", confidence=0.95)
    t = Transcript(
        visit_id=Visit(patient_id="P", clinician_id="D").id,
        raw_text="Hello",
        segments=[seg],
    )
    assert len(t.segments) == 1
    assert t.segments[0].text == "Hello"


def test_clinical_note_sections():
    note = ClinicalNote(
        visit_id=Visit(patient_id="P", clinician_id="D").id,
        sections={
            NoteSection.CHIEF_COMPLAINT: "Headache",
            NoteSection.ASSESSMENT: "Tension headache",
        },
    )
    assert note.sections[NoteSection.CHIEF_COMPLAINT] == "Headache"
    assert not note.is_approved


def test_audit_entry_immutable_concept():
    """Audit entries should capture a point in time."""
    from medscribe.domain.enums import AuditAction

    entry = AuditEntry(
        action=AuditAction.VISIT_CREATED,
        actor="DR001",
        detail={"reason": "new patient"},
    )
    assert entry.timestamp.tzinfo == timezone.utc
    assert entry.detail["reason"] == "new patient"


def test_safety_flag_defaults():
    flag = SafetyFlag(
        visit_id=Visit(patient_id="P", clinician_id="D").id,
        severity="warning",
        category="low_confidence",
        message="Check this",
    )
    assert not flag.resolved
    assert flag.resolved_by is None


def test_visit_status_serializes_to_string():
    """Enum values must be JSON-friendly strings."""
    assert VisitStatus.CREATED.value == "created"
    assert VisitStatus.APPROVED.value == "approved"


def test_note_section_serializes():
    assert NoteSection.CHIEF_COMPLAINT.value == "chief_complaint"
