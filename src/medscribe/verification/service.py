from __future__ import annotations

"""
Verification service — all business logic lives here.

The state machine enforces valid transitions:

  PENDING → IN_REVIEW → APPROVED
                      → REJECTED → PENDING (resubmit)

No route or repository ever transitions status directly.
They always go through this service.
"""

import asyncio
import secrets
import socket
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.verification import storage
from medscribe.verification.enums import (
    DocumentType,
    JobStatus,
    JobType,
    VerificationAction,
    VerificationStatus,
)
from medscribe.verification.models import (
    Verification,
    VerificationAuditEntry,
    VerificationDocument,
    VerificationJob,
)
from medscribe.verification.repository import (
    VerificationAuditRepository,
    VerificationDocumentRepository,
    VerificationJobRepository,
    VerificationRepository,
)
from medscribe.verification.security import read_and_validate_content, validate_upload

# Valid state transitions — same pattern as clinical workflow engine
_TRANSITIONS: dict[VerificationStatus, set[VerificationStatus]] = {
    VerificationStatus.PENDING: {VerificationStatus.IN_REVIEW},
    VerificationStatus.IN_REVIEW: {VerificationStatus.APPROVED, VerificationStatus.REJECTED},
    VerificationStatus.REJECTED: {VerificationStatus.PENDING},  # allow resubmit
    VerificationStatus.APPROVED: set(),  # terminal
}


def _assert_transition(current: VerificationStatus, target: VerificationStatus) -> None:
    allowed = _TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition from '{current.value}' to '{target.value}'.",
        )


def _assert_version(current: int, expected: int) -> None:
    """Optimistic locking check — raises 409 if another writer updated first."""
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Version conflict: expected version {expected}, got {current}. "
                   "Record was modified by another request. Please refresh and retry.",
        )


class VerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = VerificationRepository(session)
        self._doc_repo = VerificationDocumentRepository(session)
        self._audit = VerificationAuditRepository(session)
        self._jobs = VerificationJobRepository(session)

    async def submit(self, user_id: str, full_name: str, email: str) -> Verification:
        """Create a new verification case in PENDING state."""
        v = Verification(user_id=user_id, full_name=full_name, email=email)
        await self._repo.save(v)
        await self._audit.save(VerificationAuditEntry(
            verification_id=v.id,
            action=VerificationAction.SUBMITTED,
            actor=user_id,
            detail={"full_name": full_name, "email": email},
        ))
        return v

    async def upload_document(
        self,
        verification_id: UUID,
        document_type: DocumentType,
        file: UploadFile,
        actor: str,
    ) -> VerificationDocument:
        """Validate, store, and register a document against a verification case."""
        v = await self._get_or_404(verification_id)

        if v.status not in (VerificationStatus.PENDING, VerificationStatus.REJECTED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Documents can only be uploaded when status is pending or rejected.",
            )

        validate_upload(file)
        content = await read_and_validate_content(file)

        doc = VerificationDocument(
            verification_id=verification_id,
            document_type=document_type,
            file_name=file.filename or "upload",
            file_size_bytes=len(content),
            file_hash=VerificationDocument.compute_hash(content),
            ai_confidence=0.0,
            uploaded_by=actor,
        )

        storage.save_document(verification_id, doc.id, content, doc.file_name)
        await self._doc_repo.save(doc)
        await self._audit.save(VerificationAuditEntry(
            verification_id=verification_id,
            action=VerificationAction.DOCUMENT_UPLOADED,
            actor=actor,
            detail={"document_type": document_type.value, "file_name": doc.file_name, "file_hash": doc.file_hash},
        ))

        # Spawn a background job record for document processing (OCR + AI scoring).
        # In production this would enqueue to Celery/Redis. Here we simulate with DB state.
        job = VerificationJob(
            verification_id=verification_id,
            job_type=JobType.DOCUMENT_PROCESSING,
            status=JobStatus.PENDING,
        )
        await self._jobs.save(job)
        # Simulate job execution inline (dev mode — no real queue)
        await self._run_document_job(job, doc)

        return doc

    async def _run_document_job(self, job: VerificationJob, doc: VerificationDocument) -> None:
        """
        Simulate async document processing: OCR extraction + AI confidence scoring.
        Production: this runs in a Celery worker identified by worker_id.
        """
        job.status = JobStatus.PROCESSING
        job.worker_id = f"worker-{socket.gethostname()}"
        job.started_at = datetime.now(timezone.utc)
        await self._jobs.save(job)

        try:
            await asyncio.sleep(0)

            # Simulate AI confidence score (replace with real OCR/ML model output)
            ai_confidence = round(0.72 + secrets.randbelow(26) / 100, 2)
            doc.ai_confidence = ai_confidence
            doc.extracted_data = {
                "ai_model": "doc-classifier-v1",
                "confidence": ai_confidence,
                "confidence_threshold": 0.70,
                "passed_threshold": ai_confidence >= 0.70,
                "suggestion": "approve" if ai_confidence >= 0.70 else "manual_review",
            }
            await self._doc_repo.save(doc)

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.last_error = str(e)
            job.retry_count += 1

        await self._jobs.save(job)

    async def start_review(self, verification_id: UUID, reviewer: str, expected_version: int | None = None) -> Verification:
        """Admin moves case from PENDING → IN_REVIEW."""
        v = await self._get_or_404(verification_id)
        _assert_transition(v.status, VerificationStatus.IN_REVIEW)
        if expected_version is not None:
            _assert_version(v.version, expected_version)

        v.status = VerificationStatus.IN_REVIEW
        v.version += 1
        v.updated_at = datetime.now(timezone.utc)
        await self._repo.save(v)
        await self._audit.save(VerificationAuditEntry(
            verification_id=v.id,
            action=VerificationAction.REVIEW_STARTED,
            actor=reviewer,
        ))
        return v

    async def approve(self, verification_id: UUID, reviewer: str, expected_version: int | None = None) -> Verification:
        """Admin approves — moves IN_REVIEW → APPROVED."""
        v = await self._get_or_404(verification_id)
        _assert_transition(v.status, VerificationStatus.APPROVED)
        if expected_version is not None:
            _assert_version(v.version, expected_version)

        now = datetime.now(timezone.utc)
        v.status = VerificationStatus.APPROVED
        v.version += 1
        v.reviewed_by = reviewer
        v.reviewed_at = now
        v.updated_at = now
        await self._repo.save(v)
        await self._audit.save(VerificationAuditEntry(
            verification_id=v.id,
            action=VerificationAction.APPROVED,
            actor=reviewer,
        ))
        return v

    async def reject(self, verification_id: UUID, reviewer: str, reason: str, expected_version: int | None = None) -> Verification:
        """Admin rejects — moves IN_REVIEW → REJECTED with a reason."""
        v = await self._get_or_404(verification_id)
        _assert_transition(v.status, VerificationStatus.REJECTED)
        if expected_version is not None:
            _assert_version(v.version, expected_version)

        now = datetime.now(timezone.utc)
        v.status = VerificationStatus.REJECTED
        v.version += 1
        v.rejection_reason = reason
        v.reviewed_by = reviewer
        v.reviewed_at = now
        v.updated_at = now
        await self._repo.save(v)
        await self._audit.save(VerificationAuditEntry(
            verification_id=v.id,
            action=VerificationAction.REJECTED,
            actor=reviewer,
            detail={"reason": reason},
        ))
        return v

    async def resubmit(self, verification_id: UUID, user_id: str) -> Verification:
        """User resubmits after rejection — moves REJECTED → PENDING."""
        v = await self._get_or_404(verification_id)
        _assert_transition(v.status, VerificationStatus.PENDING)

        v.status = VerificationStatus.PENDING
        v.rejection_reason = None
        v.reviewed_by = None
        v.reviewed_at = None
        v.updated_at = datetime.now(timezone.utc)
        await self._repo.save(v)
        await self._audit.save(VerificationAuditEntry(
            verification_id=v.id,
            action=VerificationAction.RESUBMITTED,
            actor=user_id,
        ))
        return v

    async def get_with_documents(self, verification_id: UUID) -> tuple[Verification, list[VerificationDocument]]:
        v = await self._get_or_404(verification_id)
        docs = await self._doc_repo.list_by_verification(verification_id)
        return v, docs

    async def get_jobs(self, verification_id: UUID) -> list[VerificationJob]:
        await self._get_or_404(verification_id)
        return await self._jobs.list_by_verification(verification_id)

    async def get_audit_trail(self, verification_id: UUID) -> list[VerificationAuditEntry]:
        await self._get_or_404(verification_id)
        return await self._audit.list_by_verification(verification_id)

    async def _get_or_404(self, verification_id: UUID) -> Verification:
        v = await self._repo.get(verification_id)
        if not v:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Verification '{verification_id}' not found.",
            )
        return v
