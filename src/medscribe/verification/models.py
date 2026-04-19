from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from medscribe.verification.enums import DocumentType, JobStatus, JobType, VerificationAction, VerificationStatus


class VerificationDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    verification_id: UUID
    document_type: DocumentType
    file_name: str
    file_size_bytes: int
    file_hash: str  # SHA-256 — integrity guarantee
    extracted_data: dict = Field(default_factory=dict)  # OCR / parsed fields
    ai_confidence: float = 0.0  # 0.0–1.0
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uploaded_by: str

    @staticmethod
    def compute_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()


class VerificationJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    verification_id: UUID
    job_type: JobType = JobType.DOCUMENT_PROCESSING
    status: JobStatus = JobStatus.PENDING
    worker_id: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Verification(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    full_name: str
    email: str
    status: VerificationStatus = VerificationStatus.PENDING
    version: int = 1  # increments on every state change — optimistic locking
    documents: list[VerificationDocument] = Field(default_factory=list)
    rejection_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class VerificationAuditEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    verification_id: UUID
    action: VerificationAction
    actor: str
    detail: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
