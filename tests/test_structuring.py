"""
Tests for the structuring service — parsing LLM output into clinical notes.

These tests verify the parsing logic WITHOUT calling any LLM.
We mock the LLM provider to return controlled JSON responses,
then verify the structuring service handles them correctly.

Note: Post-processing adds periods and normalizes terms,
so assertions use 'in' checks rather than exact matches.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from medscribe.domain.enums import NoteSection
from medscribe.services.base import LLMResult
from medscribe.services.structuring import LLMStructuringService


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def structuring(mock_llm):
    return LLMStructuringService(mock_llm)


@pytest.mark.asyncio
async def test_valid_json_output(structuring, mock_llm):
    """LLM returns clean JSON → sections are parsed correctly."""
    mock_llm.generate.return_value = LLMResult(
        text='{"chief_complaint": "Hodepine", "history": "3 dager", "examination": "Normal", "assessment": "Tensjonshodepine", "plan": "Paracetamol", "medications": "Paracetamol 500mg", "follow_up": "2 uker"}',
        model_id="test/model",
        prompt_tokens=100,
        completion_tokens=50,
        processing_time_ms=500,
    )

    result = await structuring.structure("test transcript", {}, visit_id=uuid4())

    # Post-processing may add periods — check content is present
    assert "Hodepine" in str(result.note.sections[NoteSection.CHIEF_COMPLAINT])
    assert "Paracetamol" in str(result.note.sections[NoteSection.PLAN])
    assert result.confidence > 0.9  # All 7 sections filled


@pytest.mark.asyncio
async def test_partial_json_output(structuring, mock_llm):
    """LLM returns only some sections → missing ones default."""
    mock_llm.generate.return_value = LLMResult(
        text='{"chief_complaint": "Feber", "assessment": "Influensa"}',
        model_id="test/model",
        prompt_tokens=100,
        completion_tokens=30,
        processing_time_ms=300,
    )

    result = await structuring.structure("test transcript", {}, visit_id=uuid4())

    assert "Feber" in str(result.note.sections[NoteSection.CHIEF_COMPLAINT])
    assert result.confidence < 0.5  # Only 2/7 filled


@pytest.mark.asyncio
async def test_markdown_wrapped_json(structuring, mock_llm):
    """LLM wraps JSON in markdown code block → still parsed."""
    mock_llm.generate.return_value = LLMResult(
        text='```json\n{"chief_complaint": "Ryggsmerte", "plan": "MR"}\n```',
        model_id="test/model",
        prompt_tokens=100,
        completion_tokens=20,
        processing_time_ms=200,
    )

    result = await structuring.structure("test", {}, visit_id=uuid4())

    assert "Ryggsmerte" in str(result.note.sections[NoteSection.CHIEF_COMPLAINT])


@pytest.mark.asyncio
async def test_invalid_json_returns_empty(structuring, mock_llm):
    """LLM returns garbage → all sections empty, confidence 0."""
    mock_llm.generate.return_value = LLMResult(
        text="This is not JSON at all",
        model_id="test/model",
        prompt_tokens=100,
        completion_tokens=10,
        processing_time_ms=100,
    )

    result = await structuring.structure("test", {}, visit_id=uuid4())

    assert result.confidence == 0.0
    # Post-processing normalizes to "Ikke dokumentert."
    assert all("dokumentert" in v.lower() for v in result.note.sections.values())


@pytest.mark.asyncio
async def test_list_values_joined(structuring, mock_llm):
    """LLM returns a list for a section → joined with bullets."""
    mock_llm.generate.return_value = LLMResult(
        text='{"medications": ["Paracetamol 500mg", "Ibuprofen 400mg"], "chief_complaint": "Pain"}',
        model_id="test/model",
        prompt_tokens=100,
        completion_tokens=30,
        processing_time_ms=200,
    )

    result = await structuring.structure("test", {}, visit_id=uuid4())

    meds = str(result.note.sections[NoteSection.MEDICATIONS])
    assert "Paracetamol" in meds or "paracetamol" in meds
    assert "Ibuprofen" in meds or "ibuprofen" in meds


@pytest.mark.asyncio
async def test_model_id_captured(structuring, mock_llm):
    """The model ID from LLM response is stored in the note."""
    mock_llm.generate.return_value = LLMResult(
        text='{"chief_complaint": "Test"}',
        model_id="openai/gpt-4o",
        prompt_tokens=100,
        completion_tokens=10,
        processing_time_ms=100,
    )

    result = await structuring.structure("test", {}, visit_id=uuid4())

    assert result.note.model_id == "openai/gpt-4o"
