from __future__ import annotations

"""
Workflow engine — state machine for visit lifecycle.

This is the orchestration brain. It knows:
- What state a visit is in
- What transitions are valid
- How to trigger the next AI step

Pattern: Finite State Machine (FSM)
Each state has a set of allowed next states. Transitions are
enforced — you can't jump from CREATED to APPROVED.

Why a state machine?
1. Prevents invalid states (e.g., approving a note that doesn't exist)
2. Makes the system auditable (every transition is logged)
3. Enables retry logic (if structuring fails, stay in TRANSCRIBED)
4. Aidn uses similar multi-step workflows — this is compatible

This is NOT a heavyweight workflow engine (like Temporal or Airflow).
It's a simple, in-process state machine. If you need distributed
orchestration later, the interface stays the same.
"""

import structlog

from medscribe.domain.enums import AuditAction, VisitStatus
from medscribe.domain.models import AuditEntry, Visit

logger = structlog.get_logger()

# Valid state transitions — the edges of the state machine
TRANSITIONS: dict[VisitStatus, set[VisitStatus]] = {
    VisitStatus.CREATED: {VisitStatus.RECORDING, VisitStatus.FAILED},
    VisitStatus.RECORDING: {VisitStatus.TRANSCRIBING, VisitStatus.FAILED},
    VisitStatus.TRANSCRIBING: {VisitStatus.TRANSCRIBED, VisitStatus.FAILED},
    VisitStatus.TRANSCRIBED: {VisitStatus.STRUCTURING, VisitStatus.FAILED},
    VisitStatus.STRUCTURING: {VisitStatus.STRUCTURED, VisitStatus.FAILED},
    VisitStatus.STRUCTURED: {VisitStatus.REVIEW, VisitStatus.FAILED},
    VisitStatus.REVIEW: {VisitStatus.APPROVED, VisitStatus.STRUCTURED, VisitStatus.FAILED},
    # APPROVED and FAILED are terminal states
    VisitStatus.APPROVED: set(),
    VisitStatus.FAILED: {VisitStatus.CREATED},  # Can retry from failed
}

# Map transitions to audit actions
TRANSITION_AUDIT_MAP: dict[tuple[VisitStatus, VisitStatus], AuditAction] = {
    (VisitStatus.CREATED, VisitStatus.RECORDING): AuditAction.RECORDING_STARTED,
    (VisitStatus.RECORDING, VisitStatus.TRANSCRIBING): AuditAction.RECORDING_STOPPED,
    (VisitStatus.TRANSCRIBING, VisitStatus.TRANSCRIBED): AuditAction.TRANSCRIPTION_COMPLETED,
    (VisitStatus.TRANSCRIBED, VisitStatus.STRUCTURING): AuditAction.STRUCTURING_STARTED,
    (VisitStatus.STRUCTURING, VisitStatus.STRUCTURED): AuditAction.STRUCTURING_COMPLETED,
    (VisitStatus.REVIEW, VisitStatus.APPROVED): AuditAction.NOTE_APPROVED,
    (VisitStatus.REVIEW, VisitStatus.STRUCTURED): AuditAction.NOTE_REJECTED,
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: VisitStatus, target: VisitStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value} to {target.value}")


class WorkflowEngine:
    """
    Manages visit state transitions.

    Usage:
        engine = WorkflowEngine()
        visit, audit = engine.transition(visit, VisitStatus.RECORDING, actor="dr.smith")

    The engine:
    1. Validates the transition is allowed
    2. Updates the visit status
    3. Creates an audit entry
    4. Returns both (caller decides what to persist)

    Note: The engine does NOT persist anything. It's pure logic.
    The API layer calls the engine, then saves to the database.
    This keeps the engine testable without a DB.
    """

    def transition(
        self,
        visit: Visit,
        target: VisitStatus,
        *,
        actor: str,
        detail: dict | None = None,
    ) -> tuple[Visit, AuditEntry]:
        """
        Transition a visit to a new state.

        Returns: (updated_visit, audit_entry)
        Raises: InvalidTransitionError if transition not allowed
        """
        current = visit.status
        allowed = TRANSITIONS.get(current, set())

        if target not in allowed:
            logger.warning(
                "workflow.invalid_transition",
                visit_id=str(visit.id),
                current=current.value,
                target=target.value,
            )
            raise InvalidTransitionError(current, target)

        # Update visit
        from datetime import datetime, timezone
        visit = visit.model_copy(
            update={
                "status": target,
                "updated_at": datetime.now(timezone.utc),
            }
        )

        # Create audit entry
        audit_action = TRANSITION_AUDIT_MAP.get(
            (current, target),
            AuditAction.VISIT_CREATED,  # Fallback
        )
        audit = AuditEntry(
            visit_id=visit.id,
            action=audit_action,
            actor=actor,
            detail=detail or {"from": current.value, "to": target.value},
        )

        logger.info(
            "workflow.transition",
            visit_id=str(visit.id),
            from_state=current.value,
            to_state=target.value,
            actor=actor,
        )

        return visit, audit

    def can_transition(self, visit: Visit, target: VisitStatus) -> bool:
        """Check if a transition is valid without performing it."""
        allowed = TRANSITIONS.get(visit.status, set())
        return target in allowed

    def get_allowed_transitions(self, visit: Visit) -> set[VisitStatus]:
        """Get all valid next states for a visit."""
        return TRANSITIONS.get(visit.status, set())
