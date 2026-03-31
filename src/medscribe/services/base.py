"""
Abstract base classes for all AI services.

This is the MOST IMPORTANT file architecturally. It defines contracts
that every implementation must follow. When Aidn or any external system
integrates with you, they don't care if you use OpenAI or Llama — they
care that the interface is stable.

Design pattern: Strategy Pattern
- Define the interface (ABC)
- Implement multiple strategies (OpenAI, Ollama, etc.)
- Swap at runtime via config

This is what "model-agnostic" means in practice.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from medscribe.domain.models import ClinicalNote, Transcript


@dataclass
class STTResult:
    """Result from speech-to-text processing."""

    transcript: Transcript
    processing_time_ms: float


@dataclass
class LLMResult:
    """Result from LLM generation."""

    text: str
    model_id: str
    prompt_tokens: int
    completion_tokens: int
    processing_time_ms: float


@dataclass
class StructuringResult:
    """Result from structuring raw text into clinical note."""

    note: ClinicalNote
    confidence: float  # 0.0 - 1.0
    processing_time_ms: float


class STTProvider(ABC):
    """
    Abstract speech-to-text provider.

    To add a new STT engine (e.g., Azure Speech, Google STT):
    1. Create a new class that inherits from this
    2. Implement `transcribe()`
    3. Register it in the service factory
    """

    @abstractmethod
    async def transcribe(self, audio_data: bytes, language: str = "no") -> STTResult:
        """Convert audio bytes to transcript."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the STT service is reachable and working."""
        ...


class LLMProvider(ABC):
    """
    Abstract LLM provider.

    To add a new LLM (e.g., Claude, Gemini, local Llama):
    1. Create a new class that inherits from this
    2. Implement `generate()`
    3. Register it in the service factory

    Why async? Because LLM calls are I/O-bound (network).
    We don't want to block the event loop while waiting for OpenAI.
    """

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> LLMResult:
        """Generate text from a prompt."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify the LLM service is reachable."""
        ...


class StructuringService(ABC):
    """
    Abstract structuring service.

    Takes raw transcript text and produces a structured clinical note.
    This is separate from LLMProvider because:
    - Structuring has its own prompt engineering
    - It needs validation logic (is the output valid JSON?)
    - It might use a different model than general LLM tasks
    - You might replace it with a fine-tuned model later
    """

    @abstractmethod
    async def structure(self, transcript_text: str, visit_metadata: dict) -> StructuringResult:
        """Convert raw transcript to structured clinical note."""
        ...
