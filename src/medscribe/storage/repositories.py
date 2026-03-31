from __future__ import annotations

"""
Repository pattern — the bridge between domain models and database rows.

Why repositories?
1. Domain models (Pydantic) ≠ Database models (SQLAlchemy)
2. The domain layer should never `import sqlalchemy`
3. Repositories handle the mapping in both directions
4. This makes it trivial to swap databases or add caching

Pattern: Each aggregate root (Visit, Transcript, Note) gets its own repository.
"""

import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.domain.enums import AuditAction, NoteSection, VisitStatus
from medscribe.domain.models import (
    AuditEntry,
    ClinicalNote,
    SafetyFlag,
    Transcript,
    TranscriptSegment,
    Visit,
)
from medscribe.storage.database import (
    AuditEntryRow,
    ClinicalNoteRow,
    SafetyFlagRow,
    TranscriptRow,
    VisitRow,
)


class VisitRepository:
    """Persist and retrieve Visit entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, visit: Visit) -> None:
        row = VisitRow(
            id=str(visit.id),
            patient_id=visit.patient_id,
            clinician_id=visit.clinician_id,
            status=visit.status.value,
            metadata_json=json.dumps(visit.metadata, default=str),
            created_at=visit.created_at,
            updated_at=visit.updated_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def get(self, visit_id: UUID) -> Visit | None:
        result = await self._session.execute(
            select(VisitRow).where(VisitRow.id == str(visit_id))
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        return Visit(
            id=UUID(row.id),
            patient_id=row.patient_id,
            clinician_id=row.clinician_id,
            status=VisitStatus(row.status),
            metadata=json.loads(row.metadata_json),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_by_clinician(self, clinician_id: str) -> list[Visit]:
        result = await self._session.execute(
            select(VisitRow)
            .where(VisitRow.clinician_id == clinician_id)
            .order_by(VisitRow.created_at.desc())
        )
        return [
            Visit(
                id=UUID(row.id),
                patient_id=row.patient_id,
                clinician_id=row.clinician_id,
                status=VisitStatus(row.status),
                metadata=json.loads(row.metadata_json),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result.scalars()
        ]


class TranscriptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, transcript: Transcript) -> None:
        row = TranscriptRow(
            id=str(transcript.id),
            visit_id=str(transcript.visit_id),
            raw_text=transcript.raw_text,
            segments_json=json.dumps(
                [s.model_dump() for s in transcript.segments], default=str
            ),
            language=transcript.language,
            model_id=transcript.model_id,
            confidence=transcript.confidence,
            duration_seconds=transcript.duration_seconds,
            created_at=transcript.created_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def get_by_visit(self, visit_id: UUID) -> Transcript | None:
        result = await self._session.execute(
            select(TranscriptRow).where(TranscriptRow.visit_id == str(visit_id))
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        segments = [TranscriptSegment(**s) for s in json.loads(row.segments_json)]
        return Transcript(
            id=UUID(row.id),
            visit_id=UUID(row.visit_id),
            raw_text=row.raw_text,
            segments=segments,
            language=row.language,
            model_id=row.model_id,
            confidence=row.confidence,
            duration_seconds=row.duration_seconds,
            created_at=row.created_at,
        )


class ClinicalNoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, note: ClinicalNote) -> None:
        sections = {k.value: v for k, v in note.sections.items()}
        row = ClinicalNoteRow(
            id=str(note.id),
            visit_id=str(note.visit_id),
            sections_json=json.dumps(sections, ensure_ascii=False),
            raw_llm_output=note.raw_llm_output,
            model_id=note.model_id,
            prompt_version=note.prompt_version,
            is_approved=note.is_approved,
            approved_by=note.approved_by,
            approved_at=note.approved_at,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def get_by_visit(self, visit_id: UUID) -> ClinicalNote | None:
        result = await self._session.execute(
            select(ClinicalNoteRow).where(ClinicalNoteRow.visit_id == str(visit_id))
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        raw_sections = json.loads(row.sections_json)
        sections = {NoteSection(k): v for k, v in raw_sections.items()}
        return ClinicalNote(
            id=UUID(row.id),
            visit_id=UUID(row.visit_id),
            sections=sections,
            raw_llm_output=row.raw_llm_output,
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            is_approved=row.is_approved,
            approved_by=row.approved_by,
            approved_at=row.approved_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class AuditRepository:
    """Audit log repository — WRITE and READ only. No updates or deletes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, entry: AuditEntry) -> None:
        row = AuditEntryRow(
            id=str(entry.id),
            visit_id=str(entry.visit_id) if entry.visit_id else None,
            action=entry.action.value,
            actor=entry.actor,
            detail_json=json.dumps(entry.detail, default=str),
            model_id=entry.model_id,
            timestamp=entry.timestamp,
        )
        self._session.add(row)
        await self._session.flush()

    async def save_many(self, entries: list[AuditEntry]) -> None:
        for entry in entries:
            await self.save(entry)

    async def get_by_visit(self, visit_id: UUID) -> list[AuditEntry]:
        result = await self._session.execute(
            select(AuditEntryRow)
            .where(AuditEntryRow.visit_id == str(visit_id))
            .order_by(AuditEntryRow.timestamp)
        )
        return [
            AuditEntry(
                id=UUID(row.id),
                visit_id=UUID(row.visit_id) if row.visit_id else None,
                action=AuditAction(row.action),
                actor=row.actor,
                detail=json.loads(row.detail_json),
                model_id=row.model_id,
                timestamp=row.timestamp,
            )
            for row in result.scalars()
        ]


class SafetyFlagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, flag: SafetyFlag) -> None:
        row = SafetyFlagRow(
            id=str(flag.id),
            visit_id=str(flag.visit_id),
            severity=flag.severity,
            category=flag.category,
            message=flag.message,
            resolved=flag.resolved,
            resolved_by=flag.resolved_by,
            created_at=flag.created_at,
        )
        await self._session.merge(row)
        await self._session.flush()

    async def save_many(self, flags: list[SafetyFlag]) -> None:
        for flag in flags:
            await self.save(flag)

    async def get_by_visit(self, visit_id: UUID) -> list[SafetyFlag]:
        result = await self._session.execute(
            select(SafetyFlagRow)
            .where(SafetyFlagRow.visit_id == str(visit_id))
            .order_by(SafetyFlagRow.created_at)
        )
        return [
            SafetyFlag(
                id=UUID(row.id),
                visit_id=UUID(row.visit_id),
                severity=row.severity,
                category=row.category,
                message=row.message,
                resolved=row.resolved,
                resolved_by=row.resolved_by,
                created_at=row.created_at,
            )
            for row in result.scalars()
        ]
