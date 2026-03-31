from __future__ import annotations

"""
Agent API endpoints — agentic workflow management.

These endpoints let the frontend (or the EPJ system) interact with
the agent orchestrator:

1. POST /agent/plan — Generate a plan with previews
2. GET  /agent/plan/{id} — Get plan status and previews
3. POST /agent/plan/{id}/actions/{action_id}/approve — Approve an action
4. POST /agent/plan/{id}/actions/{action_id}/skip — Skip an action
5. POST /agent/plan/{id}/actions/{action_id}/execute — Execute an action
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from medscribe.api.auth import AuthenticatedUser, get_current_user
from medscribe.api.dependencies import get_note_repo, get_visit_repo
from medscribe.services.factory import get_llm_provider
from medscribe.storage.repositories import ClinicalNoteRepository, VisitRepository

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/agent", tags=["Agentic AI"])

# In-memory plan storage (production: use database)
_plans: dict[str, object] = {}


class PlanRequest(BaseModel):
    visit_id: UUID
    include_referral: bool = False
    include_letter: bool = False
    letter_type: str = "epikrise"


@router.post("/plan")
async def create_plan(
    request: PlanRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    visit_repo: VisitRepository = Depends(get_visit_repo),
    note_repo: ClinicalNoteRepository = Depends(get_note_repo),
):
    """
    Generate an agentic plan with AI-suggested actions.

    The plan contains previews for each action so the doctor
    can review before approving. Nothing executes automatically
    (except LOW-risk actions like code suggestions).
    """
    visit = await visit_repo.get(request.visit_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")

    note = await note_repo.get_by_visit(request.visit_id)
    if not note:
        raise HTTPException(status_code=404, detail="No note found — process visit first")

    # Build note text from sections
    note_text = "\n".join(
        f"{k.value if hasattr(k, 'value') else k}: {v}"
        for k, v in note.sections.items()
        if v and v != "Not documented."
    )

    from medscribe.agents.orchestrator import AgentOrchestrator
    llm = get_llm_provider()
    orchestrator = AgentOrchestrator(llm)

    plan = await orchestrator.plan_post_consultation(
        visit_id=request.visit_id,
        note_text=note_text,
        include_referral=request.include_referral,
        include_letter=request.include_letter,
        letter_type=request.letter_type,
    )

    # Store plan
    _plans[str(plan.id)] = plan

    return _serialize_plan(plan)


@router.get("/plan/{plan_id}")
async def get_plan(
    plan_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Get plan status, progress, and all action previews."""
    plan = _plans.get(str(plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return _serialize_plan(plan)


@router.post("/plan/{plan_id}/actions/{action_id}/approve")
async def approve_action(
    plan_id: UUID,
    action_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Approve an action — marks it ready for execution."""
    plan = _plans.get(str(plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    from medscribe.agents.orchestrator import AgentOrchestrator
    llm = get_llm_provider()
    orchestrator = AgentOrchestrator(llm)

    action = await orchestrator.approve_action(plan, action_id)
    return {"action_id": str(action.id), "status": action.status.value}


@router.post("/plan/{plan_id}/actions/{action_id}/skip")
async def skip_action(
    plan_id: UUID,
    action_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Skip an action — doctor decided it's not needed."""
    plan = _plans.get(str(plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    from medscribe.agents.orchestrator import AgentOrchestrator
    llm = get_llm_provider()
    orchestrator = AgentOrchestrator(llm)

    action = await orchestrator.skip_action(plan, action_id)
    return {"action_id": str(action.id), "status": action.status.value}


@router.post("/plan/{plan_id}/actions/{action_id}/execute")
async def execute_action(
    plan_id: UUID,
    action_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Execute an approved action."""
    plan = _plans.get(str(plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    from medscribe.agents.orchestrator import AgentOrchestrator
    llm = get_llm_provider()
    orchestrator = AgentOrchestrator(llm)

    action = await orchestrator.execute_action(plan, action_id, actor=user.user_id)
    return {
        "action_id": str(action.id),
        "status": action.status.value,
        "output": action.output_data,
        "error": action.error,
    }


# --- RAG: Patient Context Q&A ---


class AskRequest(BaseModel):
    patient_id: str = Field(min_length=1)
    question: str = Field(min_length=1)


@router.post("/ask")
async def ask_patient_context(
    request: AskRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session=Depends(lambda: None),  # Will be replaced below
):
    """
    Ask a question about a patient's history.

    Uses RAG (Retrieval-Augmented Generation) to answer
    questions based ONLY on the patient's visit notes.

    Example: "Hvilke medisiner bruker pasienten?"
    """
    from medscribe.agents.rag import PatientRAG

    # Get a real session
    factory = __import__('medscribe.storage.database', fromlist=['get_session_factory']).get_session_factory()
    async with factory() as db_session:
        llm = get_llm_provider()
        rag = PatientRAG(db_session, llm)
        answer = await rag.ask(request.question, request.patient_id)
        return answer


def _serialize_plan(plan) -> dict:
    """Serialize an AgentPlan for the API response."""
    return {
        "id": str(plan.id),
        "visit_id": str(plan.visit_id) if plan.visit_id else None,
        "name": plan.name,
        "description": plan.description,
        "status": plan.status,
        "progress": plan.progress,
        "actions": [
            {
                "id": str(a.id),
                "agent_id": a.agent_id,
                "name": a.name,
                "description": a.description,
                "risk": a.risk.value,
                "status": a.status.value,
                "preview": a.preview_data,
                "output": a.output_data,
                "error": a.error,
            }
            for a in plan.actions
        ],
    }
