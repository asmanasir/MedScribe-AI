from __future__ import annotations

"""
API request/response schemas — what the outside world sees.

These are SEPARATE from domain models. Why?
1. API schemas are versioned (v1, v2) — domain models are not
2. API schemas might expose less data than the domain
3. API schemas have validation rules specific to HTTP (e.g., max file size)
4. Domain models should never be coupled to API contracts

When the EPJ system integrates, it codes against THESE schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from medscribe.domain.enums import NoteSection, VisitStatus


# --- Requests ---


class CreateVisitRequest(BaseModel):
    patient_id: str = Field(min_length=1, max_length=255)
    clinician_id: str = Field(min_length=1, max_length=255)
    metadata: dict = Field(default_factory=dict)


class ApproveNoteRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=255)


class EditNoteRequest(BaseModel):
    sections: dict[NoteSection, str]


# --- Responses ---


class VisitResponse(BaseModel):
    id: UUID
    patient_id: str
    clinician_id: str
    status: VisitStatus
    allowed_transitions: list[VisitStatus] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    metadata: dict = Field(default_factory=dict)


class TranscriptResponse(BaseModel):
    id: UUID
    visit_id: UUID
    raw_text: str
    language: str
    model_id: str
    confidence: float
    duration_seconds: float
    segment_count: int
    created_at: datetime


class ClinicalNoteResponse(BaseModel):
    id: UUID
    visit_id: UUID
    sections: dict[NoteSection, str]
    model_id: str
    is_approved: bool
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SafetyFlagResponse(BaseModel):
    id: UUID
    severity: str
    category: str
    message: str
    resolved: bool
    created_at: datetime


class ProcessVisitResponse(BaseModel):
    """Response for the full pipeline endpoint."""

    visit: VisitResponse
    transcript: TranscriptResponse
    note: ClinicalNoteResponse
    safety_flags: list[SafetyFlagResponse] = Field(default_factory=list)


class AuditEntryResponse(BaseModel):
    id: UUID
    action: str
    actor: str
    detail: dict
    model_id: str | None
    timestamp: datetime


class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict[str, bool]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    visit_id: UUID | None = None
