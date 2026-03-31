"""
Domain enumerations — the language of your system.

These enums define the valid states and types across the platform.
They belong in the domain layer because they represent business concepts,
not technical details.
"""

from enum import Enum


class VisitStatus(str, Enum):
    """
    Visit lifecycle states. This is the core state machine.

    Flow: CREATED → RECORDING → TRANSCRIBING → TRANSCRIBED
          → STRUCTURING → STRUCTURED → REVIEW → APPROVED

    Why string enum? So it serializes cleanly to JSON for the API
    and stores as text in the database (readable, not magic ints).
    """

    CREATED = "created"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    STRUCTURING = "structuring"
    STRUCTURED = "structured"
    REVIEW = "review"
    APPROVED = "approved"
    FAILED = "failed"


class NoteSection(str, Enum):
    """
    Standard clinical note sections (SOAP-ish).

    These map to what clinicians expect. The structuring module
    must produce output that maps to these sections.
    """

    CHIEF_COMPLAINT = "chief_complaint"
    HISTORY = "history"
    EXAMINATION = "examination"
    ASSESSMENT = "assessment"
    PLAN = "plan"
    MEDICATIONS = "medications"
    FOLLOW_UP = "follow_up"


class AuditAction(str, Enum):
    """Every auditable action in the system. Required for healthcare compliance."""

    VISIT_CREATED = "visit.created"
    RECORDING_STARTED = "recording.started"
    RECORDING_STOPPED = "recording.stopped"
    TRANSCRIPTION_STARTED = "transcription.started"
    TRANSCRIPTION_COMPLETED = "transcription.completed"
    STRUCTURING_STARTED = "structuring.started"
    STRUCTURING_COMPLETED = "structuring.completed"
    NOTE_EDITED = "note.edited"
    NOTE_APPROVED = "note.approved"
    NOTE_REJECTED = "note.rejected"
    SAFETY_FLAG_RAISED = "safety.flag_raised"
