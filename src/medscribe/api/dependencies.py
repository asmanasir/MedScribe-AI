"""
FastAPI dependency injection — the wiring of the API layer.

FastAPI's `Depends()` system is a built-in dependency injection framework.
It's how we pass services, DB sessions, and auth context to route handlers
without global state.

Why DI matters:
- Route handlers are thin (just call services)
- Easy to mock in tests (override dependencies)
- No global mutable state
- Services are created per-request or cached as needed
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from medscribe.config import Settings, get_settings
from medscribe.safety.guardrails import SafetyGuardrails
from medscribe.services.base import StructuringService, STTProvider
from medscribe.services.factory import (
    get_structuring_service,
    get_stt_provider,
)
from medscribe.storage.database import get_session_factory
from medscribe.storage.repositories import (
    AuditRepository,
    ClinicalNoteRepository,
    SafetyFlagRepository,
    TranscriptRepository,
    VisitRepository,
)
from medscribe.workflow.engine import WorkflowEngine
from medscribe.workflow.orchestrator import VisitOrchestrator


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a DB session per request. Auto-commits on success, rollbacks on error.

    This is the "unit of work" pattern — one transaction per HTTP request.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_visit_repo(session: AsyncSession = Depends(get_db_session)) -> VisitRepository:
    return VisitRepository(session)


def get_transcript_repo(session: AsyncSession = Depends(get_db_session)) -> TranscriptRepository:
    return TranscriptRepository(session)


def get_note_repo(session: AsyncSession = Depends(get_db_session)) -> ClinicalNoteRepository:
    return ClinicalNoteRepository(session)


def get_audit_repo(session: AsyncSession = Depends(get_db_session)) -> AuditRepository:
    return AuditRepository(session)


def get_safety_flag_repo(session: AsyncSession = Depends(get_db_session)) -> SafetyFlagRepository:
    return SafetyFlagRepository(session)


def get_workflow_engine() -> WorkflowEngine:
    return WorkflowEngine()


def get_guardrails(settings: Settings = Depends(get_settings)) -> SafetyGuardrails:
    return SafetyGuardrails(settings)


def get_orchestrator(
    stt: STTProvider = Depends(get_stt_provider),
    structuring: StructuringService = Depends(get_structuring_service),
) -> VisitOrchestrator:
    return VisitOrchestrator(
        workflow=WorkflowEngine(),
        stt=stt,
        structuring=structuring,
    )
