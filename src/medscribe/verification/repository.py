from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.storage.database import (
    VerificationAuditRow,
    VerificationDocumentRow,
    VerificationJobRow,
    VerificationRow,
)
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


class VerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, v: Verification) -> None:
        row = VerificationRow(
            id=str(v.id),
            user_id=v.user_id,
            full_name=v.full_name,
            email=v.email,
            status=v.status.value,
            version=v.version,
            rejection_reason=v.rejection_reason,
            reviewed_by=v.reviewed_by,
            reviewed_at=v.reviewed_at,
            created_at=v.created_at,
            updated_at=v.updated_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def get(self, verification_id: UUID) -> Verification | None:
        result = await self._session.execute(
            select(VerificationRow).where(VerificationRow.id == str(verification_id))
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._row_to_model(row)

    async def list_by_user(self, user_id: str) -> list[Verification]:
        result = await self._session.execute(
            select(VerificationRow)
            .where(VerificationRow.user_id == user_id)
            .order_by(VerificationRow.created_at.desc())
        )
        return [self._row_to_model(r) for r in result.scalars()]

    async def list_all(self, status: VerificationStatus | None = None) -> list[Verification]:
        q = select(VerificationRow).order_by(VerificationRow.created_at.desc())
        if status:
            q = q.where(VerificationRow.status == status.value)
        result = await self._session.execute(q)
        return [self._row_to_model(r) for r in result.scalars()]

    def _row_to_model(self, row: VerificationRow) -> Verification:
        return Verification(
            id=UUID(row.id),
            user_id=row.user_id,
            full_name=row.full_name,
            email=row.email,
            status=VerificationStatus(row.status),
            version=row.version,
            rejection_reason=row.rejection_reason,
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class VerificationDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, doc: VerificationDocument) -> None:
        row = VerificationDocumentRow(
            id=str(doc.id),
            verification_id=str(doc.verification_id),
            document_type=doc.document_type.value,
            file_name=doc.file_name,
            file_size_bytes=doc.file_size_bytes,
            file_hash=doc.file_hash,
            extracted_data_json=json.dumps(doc.extracted_data, ensure_ascii=False),
            ai_confidence=doc.ai_confidence,
            uploaded_at=doc.uploaded_at,
            uploaded_by=doc.uploaded_by,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def list_by_verification(self, verification_id: UUID) -> list[VerificationDocument]:
        result = await self._session.execute(
            select(VerificationDocumentRow)
            .where(VerificationDocumentRow.verification_id == str(verification_id))
            .order_by(VerificationDocumentRow.uploaded_at)
        )
        return [
            VerificationDocument(
                id=UUID(r.id),
                verification_id=UUID(r.verification_id),
                document_type=DocumentType(r.document_type),
                file_name=r.file_name,
                file_size_bytes=r.file_size_bytes,
                file_hash=r.file_hash,
                extracted_data=json.loads(r.extracted_data_json),
                ai_confidence=r.ai_confidence,
                uploaded_at=r.uploaded_at,
                uploaded_by=r.uploaded_by,
            )
            for r in result.scalars()
        ]


class VerificationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, job: VerificationJob) -> None:
        row = VerificationJobRow(
            id=str(job.id),
            verification_id=str(job.verification_id),
            job_type=job.job_type.value,
            status=job.status.value,
            worker_id=job.worker_id,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            last_error=job.last_error,
            started_at=job.started_at,
            completed_at=job.completed_at,
            created_at=job.created_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def get_latest(self, verification_id: UUID) -> VerificationJob | None:
        result = await self._session.execute(
            select(VerificationJobRow)
            .where(VerificationJobRow.verification_id == str(verification_id))
            .order_by(VerificationJobRow.created_at.desc())
        )
        row = result.scalars().first()
        if not row:
            return None
        return self._row_to_model(row)

    async def list_by_verification(self, verification_id: UUID) -> list[VerificationJob]:
        result = await self._session.execute(
            select(VerificationJobRow)
            .where(VerificationJobRow.verification_id == str(verification_id))
            .order_by(VerificationJobRow.created_at.desc())
        )
        return [self._row_to_model(r) for r in result.scalars()]

    def _row_to_model(self, row: VerificationJobRow) -> VerificationJob:
        return VerificationJob(
            id=UUID(row.id),
            verification_id=UUID(row.verification_id),
            job_type=JobType(row.job_type),
            status=JobStatus(row.status),
            worker_id=row.worker_id,
            retry_count=row.retry_count,
            max_retries=row.max_retries,
            last_error=row.last_error,
            started_at=row.started_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
        )


class VerificationAuditRepository:
    """Append-only audit log for verification actions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, entry: VerificationAuditEntry) -> None:
        row = VerificationAuditRow(
            id=str(entry.id),
            verification_id=str(entry.verification_id),
            action=entry.action.value,
            actor=entry.actor,
            detail_json=json.dumps(entry.detail, default=str),
            timestamp=entry.timestamp,
        )
        self._session.add(row)
        await self._session.flush()

    async def list_by_verification(self, verification_id: UUID) -> list[VerificationAuditEntry]:
        result = await self._session.execute(
            select(VerificationAuditRow)
            .where(VerificationAuditRow.verification_id == str(verification_id))
            .order_by(VerificationAuditRow.timestamp)
        )
        return [
            VerificationAuditEntry(
                id=UUID(r.id),
                verification_id=UUID(r.verification_id),
                action=VerificationAction(r.action),
                actor=r.actor,
                detail=json.loads(r.detail_json),
                timestamp=r.timestamp,
            )
            for r in result.scalars()
        ]
