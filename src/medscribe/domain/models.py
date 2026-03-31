from __future__ import annotations

"""
Domain models — the core business objects of MedScribe.

Design decisions:
1. These are Pydantic models, NOT SQLAlchemy models. Why?
   - Domain models are framework-independent
   - We map to/from DB models in the storage layer
   - This lets us change the DB without touching business logic

2. Every model has `created_at` and `updated_at`. In healthcare,
   you MUST know when everything happened.

3. IDs are UUIDs, not auto-increment ints. Why?
   - Can be generated client-side (no DB round-trip)
   - Safe to expose in URLs (no enumeration attacks)
   - Works across distributed systems
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from medscribe.domain.enums import AuditAction, NoteSection, VisitStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Visit(BaseModel):
    """
    A clinical visit / encounter. This is the top-level entity.
    Everything else (transcript, note) hangs off a visit.
    """

    id: UUID = Field(default_factory=uuid4)
    patient_id: str  # External ID — we don't store patient data
    clinician_id: str
    status: VisitStatus = VisitStatus.CREATED
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict = Field(default_factory=dict)  # Extensible — Aidn can pass extra data


class Transcript(BaseModel):
    """
    Raw transcription output from STT service.

    We store the raw text AND per-segment data (with timestamps).
    This allows:
    - Reviewing what the AI "heard"
    - Debugging bad structuring
    - Audit trail
    """

    id: UUID = Field(default_factory=uuid4)
    visit_id: UUID
    raw_text: str
    segments: list["TranscriptSegment"] = Field(default_factory=list)
    language: str = "no"  # Norwegian default
    model_id: str = ""  # Which STT model produced this
    confidence: float = 0.0  # Overall confidence score
    duration_seconds: float = 0.0
    created_at: datetime = Field(default_factory=_utcnow)


class TranscriptSegment(BaseModel):
    """A timestamped chunk of the transcript."""

    start: float  # seconds
    end: float
    text: str
    confidence: float = 0.0
    speaker: str | None = None  # For future speaker diarization


class ClinicalNote(BaseModel):
    """
    Structured clinical note — the main output of the system.

    This is what gets reviewed by the clinician and potentially
    sent back to Aidn / the EPJ system.
    """

    id: UUID = Field(default_factory=uuid4)
    visit_id: UUID
    sections: dict[NoteSection, str] = Field(default_factory=dict)
    raw_llm_output: str = ""  # What the LLM actually returned (for debugging)
    model_id: str = ""  # Which LLM produced this
    prompt_version: str = ""  # Track prompt versions for reproducibility
    is_approved: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AuditEntry(BaseModel):
    """
    Immutable audit log entry. These are APPEND-ONLY.

    In healthcare, you must be able to answer:
    - Who did what?
    - When did they do it?
    - What was the input/output?
    - Which AI model was involved?

    This model captures all of that.
    """

    id: UUID = Field(default_factory=uuid4)
    visit_id: UUID | None = None
    action: AuditAction
    actor: str  # user ID or "system"
    detail: dict = Field(default_factory=dict)  # Action-specific payload
    model_id: str | None = None  # Which AI model, if applicable
    timestamp: datetime = Field(default_factory=_utcnow)


class SafetyFlag(BaseModel):
    """
    Raised when the safety layer detects an issue.

    Examples:
    - LLM output mentions a drug interaction
    - Confidence score below threshold
    - Potential hallucination detected
    """

    id: UUID = Field(default_factory=uuid4)
    visit_id: UUID
    severity: str  # "warning" | "critical"
    category: str  # e.g., "low_confidence", "hallucination_risk"
    message: str
    resolved: bool = False
    resolved_by: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
