from __future__ import annotations

"""
Agent framework — the foundation for agentic AI workflows.

What is an "agent" in healthcare AI?
Unlike simple API calls (input → output), an agent can:
1. PLAN — decide what steps are needed
2. EXECUTE — run multiple actions in sequence
3. OBSERVE — check results and adapt
4. ASK — request human approval before risky actions

Example agentic workflow:
  Doctor finishes consultation →
    Agent plans: [transcribe, structure, check_referral_needed, draft_referral, create_followup]
    Agent executes step 1: transcribe audio ✓
    Agent executes step 2: structure note ✓
    Agent observes: patient needs referral to specialist
    Agent proposes step 3: draft referral letter → PREVIEW for doctor
    Doctor approves → Agent executes
    Agent proposes step 4: create follow-up task → PREVIEW for doctor
    Doctor approves → Agent executes
    Done. All actions audited.

Key design decisions:
- Every action has a PREVIEW before execution (human-in-the-loop)
- Every action is logged in the audit trail
- Actions are reversible where possible
- The agent NEVER makes clinical decisions — it drafts, the human decides
- Risk levels: LOW (auto-execute) / MEDIUM (preview) / HIGH (require approval)

This implements agentic workflows with strict safety
boundaries and transparency.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class ActionRisk(str, Enum):
    """Risk level determines human-in-the-loop behavior."""
    LOW = "low"          # Auto-execute (e.g., transcribe, structure)
    MEDIUM = "medium"    # Show preview, ask approval (e.g., draft letter)
    HIGH = "high"        # Require explicit approval + reason (e.g., send to EPJ)


class ActionStatus(str, Enum):
    PLANNED = "planned"
    PREVIEW = "preview"       # Waiting for human review
    APPROVED = "approved"     # Human approved, ready to execute
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"       # Human decided to skip
    ROLLED_BACK = "rolled_back"


@dataclass
class AgentAction:
    """A single action in an agentic workflow."""
    id: UUID = field(default_factory=uuid4)
    agent_id: str = ""              # Which agent type
    name: str = ""                  # Human-readable name
    description: str = ""           # What this action will do
    risk: ActionRisk = ActionRisk.LOW
    status: ActionStatus = ActionStatus.PLANNED

    # Input/output
    input_data: dict = field(default_factory=dict)
    preview_data: dict | None = None    # What the human sees before approving
    output_data: dict | None = None     # Result after execution

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    executed_at: datetime | None = None
    executed_by: str | None = None      # "system" or user ID
    error: str | None = None


@dataclass
class AgentPlan:
    """A complete plan with ordered actions."""
    id: UUID = field(default_factory=uuid4)
    visit_id: UUID | None = None
    name: str = ""
    description: str = ""
    actions: list[AgentAction] = field(default_factory=list)
    status: str = "planned"  # planned, in_progress, completed, failed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def current_action(self) -> AgentAction | None:
        """Get the next action that needs processing."""
        for action in self.actions:
            if action.status in (ActionStatus.PLANNED, ActionStatus.PREVIEW, ActionStatus.APPROVED):
                return action
        return None

    @property
    def needs_approval(self) -> bool:
        """Check if any action is waiting for human approval."""
        return any(a.status == ActionStatus.PREVIEW for a in self.actions)

    @property
    def progress(self) -> dict:
        total = len(self.actions)
        completed = sum(1 for a in self.actions if a.status == ActionStatus.COMPLETED)
        return {"total": total, "completed": completed, "percent": int(completed / total * 100) if total else 0}


class Agent(ABC):
    """
    Base class for all agents.

    Each agent knows how to:
    1. Generate a preview (what it WOULD do)
    2. Execute (actually do it)
    3. Roll back (undo if possible)
    """

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique identifier for this agent type."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
        ...

    @property
    def risk(self) -> ActionRisk:
        """Default risk level. Override for high-risk agents."""
        return ActionRisk.MEDIUM

    @abstractmethod
    async def preview(self, context: dict) -> dict:
        """
        Generate a preview of what this agent would do.
        Returns data that the human can review before approving.
        """
        ...

    @abstractmethod
    async def execute(self, context: dict) -> dict:
        """Execute the action. Called after human approval (if needed)."""
        ...

    async def rollback(self, context: dict, output: dict) -> bool:
        """Undo the action if possible. Default: not rollbackable."""
        return False
