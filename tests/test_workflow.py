"""
Tests for the workflow engine.

Notice: NO database, NO API, NO AI calls.
The engine is pure logic, so tests are fast and deterministic.
This is why we separated the engine from the orchestrator.
"""

import pytest

from medscribe.domain.enums import VisitStatus
from medscribe.domain.models import Visit
from medscribe.workflow.engine import InvalidTransitionError, WorkflowEngine


@pytest.fixture
def engine():
    return WorkflowEngine()


@pytest.fixture
def visit():
    return Visit(patient_id="P001", clinician_id="DR001")


def test_valid_transition(engine, visit):
    """CREATED → RECORDING is valid."""
    updated, audit = engine.transition(visit, VisitStatus.RECORDING, actor="DR001")

    assert updated.status == VisitStatus.RECORDING
    assert audit.actor == "DR001"
    assert audit.visit_id == visit.id


def test_invalid_transition(engine, visit):
    """CREATED → APPROVED is NOT valid (can't skip steps)."""
    with pytest.raises(InvalidTransitionError):
        engine.transition(visit, VisitStatus.APPROVED, actor="DR001")


def test_full_happy_path(engine, visit):
    """Walk through the entire lifecycle."""
    states = [
        VisitStatus.RECORDING,
        VisitStatus.TRANSCRIBING,
        VisitStatus.TRANSCRIBED,
        VisitStatus.STRUCTURING,
        VisitStatus.STRUCTURED,
        VisitStatus.REVIEW,
        VisitStatus.APPROVED,
    ]

    for target in states:
        visit, _ = engine.transition(visit, target, actor="DR001")
        assert visit.status == target

    # APPROVED is terminal — no transitions allowed
    assert engine.get_allowed_transitions(visit) == set()


def test_failed_state_allows_retry(engine, visit):
    """A failed visit can restart from CREATED."""
    visit, _ = engine.transition(visit, VisitStatus.RECORDING, actor="DR001")
    visit, _ = engine.transition(visit, VisitStatus.FAILED, actor="system")
    visit, _ = engine.transition(visit, VisitStatus.CREATED, actor="system")

    assert visit.status == VisitStatus.CREATED


def test_can_transition_check(engine, visit):
    """can_transition returns True/False without side effects."""
    assert engine.can_transition(visit, VisitStatus.RECORDING) is True
    assert engine.can_transition(visit, VisitStatus.APPROVED) is False


def test_review_allows_rejection(engine):
    """From REVIEW, clinician can reject back to STRUCTURED."""
    visit = Visit(patient_id="P001", clinician_id="DR001", status=VisitStatus.REVIEW)
    visit, audit = engine.transition(visit, VisitStatus.STRUCTURED, actor="DR001")

    assert visit.status == VisitStatus.STRUCTURED
