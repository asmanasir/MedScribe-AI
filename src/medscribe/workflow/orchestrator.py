from __future__ import annotations

"""
Visit orchestrator — the "conductor" that ties everything together.

The orchestrator knows the high-level flow:
1. Receive audio → transcribe (STT)
2. Transcription → structure (LLM)
3. Structured note → review (human)

It calls the workflow engine for state transitions and the
AI services for processing. It's the glue between layers.

Why separate from the workflow engine?
- Engine = pure state machine logic (no I/O, no AI)
- Orchestrator = coordination (calls services, handles errors)
- This means you can unit-test the engine without mocking AI services
"""

import structlog

from medscribe.domain.enums import VisitStatus
from medscribe.domain.models import AuditEntry, ClinicalNote, Transcript, Visit
from medscribe.services.base import STTProvider, StructuringService
from medscribe.workflow.engine import WorkflowEngine

logger = structlog.get_logger()


class VisitOrchestrator:
    """
    Orchestrates the full visit processing pipeline.

    Dependencies are injected — the orchestrator doesn't know
    which STT or structuring implementation it's using.
    """

    def __init__(
        self,
        workflow: WorkflowEngine,
        stt: STTProvider,
        structuring: StructuringService,
    ) -> None:
        self._workflow = workflow
        self._stt = stt
        self._structuring = structuring

    async def process_audio(
        self,
        visit: Visit,
        audio_data: bytes,
        *,
        actor: str,
        language: str = "no",
    ) -> tuple[Visit, Transcript, list[AuditEntry]]:
        """
        Full audio → transcript pipeline.

        Steps:
        1. Transition to TRANSCRIBING
        2. Run STT
        3. Transition to TRANSCRIBED
        4. Return results + audit trail

        The caller (API layer) persists everything.
        """
        audits: list[AuditEntry] = []

        # Step 1a: Transition to RECORDING if needed (visit just created)
        if visit.status == VisitStatus.CREATED:
            visit, audit = self._workflow.transition(
                visit, VisitStatus.RECORDING, actor=actor
            )
            audits.append(audit)

        # Step 1b: Transition to TRANSCRIBING
        visit, audit = self._workflow.transition(
            visit, VisitStatus.TRANSCRIBING, actor=actor
        )
        audits.append(audit)

        # Step 2: Run STT
        try:
            result = await self._stt.transcribe(
                audio_data, language, visit_id=visit.id
            )
            transcript = result.transcript
        except Exception as e:
            logger.error("orchestrator.stt_failed", visit_id=str(visit.id), error=str(e))
            visit, audit = self._workflow.transition(
                visit, VisitStatus.FAILED, actor="system",
                detail={"error": f"STT failed: {e}"},
            )
            audits.append(audit)
            raise

        # Step 3: Mark as transcribed
        visit, audit = self._workflow.transition(
            visit, VisitStatus.TRANSCRIBED, actor="system",
            detail={
                "duration_seconds": transcript.duration_seconds,
                "segments": len(transcript.segments),
            },
        )
        audits.append(audit)

        return visit, transcript, audits

    async def structure_transcript(
        self,
        visit: Visit,
        transcript: Transcript,
        *,
        actor: str,
    ) -> tuple[Visit, ClinicalNote, list[AuditEntry]]:
        """
        Full transcript → structured note pipeline.

        Steps:
        1. Transition to STRUCTURING
        2. Run structuring
        3. Transition to STRUCTURED → REVIEW
        4. Return results + audit trail
        """
        audits: list[AuditEntry] = []

        # Step 1: Start structuring
        visit, audit = self._workflow.transition(
            visit, VisitStatus.STRUCTURING, actor=actor
        )
        audits.append(audit)

        # Step 2: Run structuring
        try:
            result = await self._structuring.structure(
                transcript.raw_text,
                visit.metadata,
                visit_id=visit.id,
            )
            note = result.note
        except Exception as e:
            logger.error("orchestrator.structuring_failed", visit_id=str(visit.id), error=str(e))
            visit, audit = self._workflow.transition(
                visit, VisitStatus.FAILED, actor="system",
                detail={"error": f"Structuring failed: {e}"},
            )
            audits.append(audit)
            raise

        # Step 3: Mark as structured
        visit, audit = self._workflow.transition(
            visit, VisitStatus.STRUCTURED, actor="system",
            detail={"confidence": result.confidence, "model": note.model_id},
        )
        audits.append(audit)

        # Step 4: Move to review (human-in-the-loop)
        visit, audit = self._workflow.transition(
            visit, VisitStatus.REVIEW, actor="system"
        )
        audits.append(audit)

        return visit, note, audits

    async def process_visit(
        self,
        visit: Visit,
        audio_data: bytes,
        *,
        actor: str,
        language: str = "no",
    ) -> tuple[Visit, Transcript, ClinicalNote, list[AuditEntry]]:
        """
        Full pipeline: audio → transcript → structured note → review.

        This is the "one-shot" endpoint for processing a complete visit.
        """
        # Transcribe
        visit, transcript, audits = await self.process_audio(
            visit, audio_data, actor=actor, language=language
        )

        # Structure
        visit, note, structure_audits = await self.structure_transcript(
            visit, transcript, actor=actor
        )
        audits.extend(structure_audits)

        return visit, transcript, note, audits
