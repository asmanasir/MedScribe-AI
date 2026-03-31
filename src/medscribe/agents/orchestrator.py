from __future__ import annotations

"""
Agent Orchestrator — the brain that chains agents into multi-step workflows.

This implements controlled, goal-driven automation where the
system can propose and chain steps.

How it works:
1. Doctor finishes a consultation
2. Orchestrator analyzes the note and PLANS which agents to run
3. Each agent generates a PREVIEW
4. Doctor reviews and approves/skips each step
5. Approved actions are executed
6. Everything is audit-logged

Workflow examples:
- "Post-consultation": transcribe → structure → suggest codes → draft referral → create follow-up
- "Quick note": transcribe → structure → approve
- "Referral pathway": structure → draft referral → send to EPJ
- "Discharge": structure → draft epikrise → update care plan → create follow-up

The orchestrator is REACTIVE — it suggests actions based on the note content.
It does NOT make clinical decisions. The human decides.
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog

from medscribe.agents.base import (
    ActionRisk,
    ActionStatus,
    Agent,
    AgentAction,
    AgentPlan,
)
from medscribe.services.base import LLMProvider

logger = structlog.get_logger()


# Agent registry — maps agent_id to agent class
_AGENT_REGISTRY: dict[str, type[Agent]] = {}


def register_agent(agent_class: type[Agent]) -> type[Agent]:
    """Decorator to register an agent in the global registry."""
    # Create a temporary instance to get the agent_id
    # We'll instantiate properly later with dependencies
    _AGENT_REGISTRY[agent_class.__name__] = agent_class
    return agent_class


class AgentOrchestrator:
    """
    Orchestrates multi-step agentic workflows.

    Usage:
        orchestrator = AgentOrchestrator(llm)
        plan = await orchestrator.plan_post_consultation(visit_id, note_text)
        # Returns a plan with previews for each action
        # Human reviews and approves each action
        # Then: await orchestrator.execute_action(plan, action_id)
    """

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm
        self._agents = self._create_agents()

    def _create_agents(self) -> dict[str, Agent]:
        from medscribe.agents.clinical import (
            CarePlanAgent,
            CodingAgent,
            FollowUpAgent,
            LetterDraftAgent,
            ReferralDraftAgent,
        )
        return {
            "referral_draft": ReferralDraftAgent(self._llm),
            "follow_up": FollowUpAgent(self._llm),
            "care_plan": CarePlanAgent(self._llm),
            "coding": CodingAgent(self._llm),
            "letter_draft": LetterDraftAgent(self._llm),
        }

    async def plan_post_consultation(
        self,
        visit_id: UUID,
        note_text: str,
        *,
        include_referral: bool = False,
        include_letter: bool = False,
        letter_type: str = "epikrise",
    ) -> AgentPlan:
        """
        Create a plan for post-consultation workflow.

        Analyzes the note and decides which agents to run.
        Each action gets a preview so the doctor can approve/skip.
        """
        plan = AgentPlan(
            visit_id=visit_id,
            name="Etterbehandling / Post-consultation",
            description="AI-foreslåtte tiltak basert på konsultasjonsnotatet",
        )

        context = {"note_text": note_text, "visit_id": str(visit_id)}

        # 1. Always suggest diagnosis codes (low risk, auto-preview)
        coding_agent = self._agents["coding"]
        coding_preview = await coding_agent.preview(context)
        plan.actions.append(AgentAction(
            agent_id="coding",
            name="Foreslå diagnosekoder",
            description="Foreslår ICD-10 koder basert på notatet",
            risk=ActionRisk.LOW,
            status=ActionStatus.PREVIEW,
            input_data=context,
            preview_data=coding_preview,
        ))

        # 2. Always suggest follow-up tasks
        followup_agent = self._agents["follow_up"]
        followup_preview = await followup_agent.preview(context)
        plan.actions.append(AgentAction(
            agent_id="follow_up",
            name="Oppfølgingstiltak",
            description="Foreslår oppfølgingstiltak basert på notatet",
            risk=ActionRisk.MEDIUM,
            status=ActionStatus.PREVIEW,
            input_data=context,
            preview_data=followup_preview,
        ))

        # 3. Referral if requested or detected
        if include_referral or self._detect_referral_need(note_text):
            referral_agent = self._agents["referral_draft"]
            referral_context = {**context, "referral_reason": "Vurdering hos spesialist"}
            referral_preview = await referral_agent.preview(referral_context)
            plan.actions.append(AgentAction(
                agent_id="referral_draft",
                name="Utkast til henvisning",
                description="Skriver utkast til henvisning til spesialist",
                risk=ActionRisk.MEDIUM,
                status=ActionStatus.PREVIEW,
                input_data=referral_context,
                preview_data=referral_preview,
            ))

        # 4. Letter draft if requested
        if include_letter:
            letter_agent = self._agents["letter_draft"]
            letter_context = {**context, "letter_type": letter_type}
            letter_preview = await letter_agent.preview(letter_context)
            plan.actions.append(AgentAction(
                agent_id="letter_draft",
                name=f"Brevutkast ({letter_type})",
                description=f"Skriver utkast til {letter_type}",
                risk=ActionRisk.MEDIUM,
                status=ActionStatus.PREVIEW,
                input_data=letter_context,
                preview_data=letter_preview,
            ))

        # 5. Care plan update suggestion
        care_agent = self._agents["care_plan"]
        care_preview = await care_agent.preview(context)
        plan.actions.append(AgentAction(
            agent_id="care_plan",
            name="Behandlingsplan-oppdatering",
            description="Foreslår endringer i behandlingsplanen",
            risk=ActionRisk.MEDIUM,
            status=ActionStatus.PREVIEW,
            input_data=context,
            preview_data=care_preview,
        ))

        plan.status = "preview"

        logger.info(
            "agent.plan_created",
            visit_id=str(visit_id),
            action_count=len(plan.actions),
            actions=[a.agent_id for a in plan.actions],
        )

        return plan

    async def execute_action(self, plan: AgentPlan, action_id: UUID, *, actor: str) -> AgentAction:
        """Execute a single approved action from the plan."""
        action = next((a for a in plan.actions if a.id == action_id), None)
        if not action:
            raise ValueError(f"Action {action_id} not found in plan")

        if action.status not in (ActionStatus.APPROVED, ActionStatus.PREVIEW):
            raise ValueError(f"Action {action_id} is {action.status}, cannot execute")

        agent = self._agents.get(action.agent_id)
        if not agent:
            raise ValueError(f"Unknown agent: {action.agent_id}")

        action.status = ActionStatus.EXECUTING
        try:
            context = {**action.input_data, "preview_data": action.preview_data}
            output = await agent.execute(context)
            action.output_data = output
            action.status = ActionStatus.COMPLETED
            action.executed_at = datetime.now(timezone.utc)
            action.executed_by = actor

            logger.info(
                "agent.action_executed",
                action_id=str(action.id),
                agent=action.agent_id,
                actor=actor,
            )
        except Exception as e:
            action.status = ActionStatus.FAILED
            action.error = str(e)
            logger.error("agent.action_failed", action_id=str(action.id), error=str(e))

        # Check if all actions are done
        if all(a.status in (ActionStatus.COMPLETED, ActionStatus.SKIPPED, ActionStatus.FAILED) for a in plan.actions):
            plan.status = "completed"

        return action

    async def approve_action(self, plan: AgentPlan, action_id: UUID) -> AgentAction:
        """Approve an action for execution."""
        action = next((a for a in plan.actions if a.id == action_id), None)
        if not action:
            raise ValueError(f"Action {action_id} not found")
        action.status = ActionStatus.APPROVED
        return action

    async def skip_action(self, plan: AgentPlan, action_id: UUID) -> AgentAction:
        """Skip an action — doctor decided it's not needed."""
        action = next((a for a in plan.actions if a.id == action_id), None)
        if not action:
            raise ValueError(f"Action {action_id} not found")
        action.status = ActionStatus.SKIPPED
        return action

    def _detect_referral_need(self, note_text: str) -> bool:
        """Simple heuristic to detect if a referral might be needed."""
        referral_keywords = [
            "henvisning", "henvis", "spesialist", "sykehus",
            "røntgen", "MR", "CT", "blodprøve", "ultralyd",
            "operasjon", "kirurg", "ortoped", "nevro",
            "psykolog", "psykiater", "øyelege", "ØNH",
        ]
        text_lower = note_text.lower()
        return any(kw.lower() in text_lower for kw in referral_keywords)
