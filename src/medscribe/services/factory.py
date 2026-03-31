from __future__ import annotations

"""
Service factory — creates the right implementation based on config.

This is the wiring layer. Instead of scattering `if config.backend == "openai"`
throughout your code, you centralize it here.

Pattern: Factory + Dependency Injection
- Factory creates instances based on config
- FastAPI's Depends() injects them into route handlers
- Tests can override with mock implementations
"""

from functools import lru_cache

from medscribe.config import LLMBackend, STTBackend, Settings, get_settings
from medscribe.services.base import LLMProvider, STTProvider, StructuringService
from medscribe.services.llm_ollama import OllamaLLMProvider
from medscribe.services.llm_openai import OpenAILLMProvider
from medscribe.services.stt_local import LocalWhisperSTTProvider
from medscribe.services.stt_whisper import WhisperSTTProvider
from medscribe.services.structuring import LLMStructuringService


@lru_cache
def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """
    Create the LLM provider based on config.

    To add a new provider:
    1. Implement LLMProvider in a new file
    2. Add a new LLMBackend enum value
    3. Add a case here
    """
    settings = settings or get_settings()

    if settings.llm_backend == LLMBackend.OPENAI:
        return OpenAILLMProvider(settings)
    elif settings.llm_backend == LLMBackend.OLLAMA:
        return OllamaLLMProvider(settings)
    else:
        raise ValueError(f"Unknown LLM backend: {settings.llm_backend}")


@lru_cache
def get_stt_provider(settings: Settings | None = None) -> STTProvider:
    """
    Create the STT provider based on config.

    LOCAL (default) → faster-whisper, audio stays on device
    OPENAI → cloud Whisper API, audio sent to OpenAI
    """
    settings = settings or get_settings()

    if settings.stt_backend == STTBackend.LOCAL:
        return LocalWhisperSTTProvider(settings)
    elif settings.stt_backend == STTBackend.OPENAI:
        return WhisperSTTProvider(settings)
    else:
        raise ValueError(f"Unknown STT backend: {settings.stt_backend}")


@lru_cache
def get_structuring_service(settings: Settings | None = None) -> StructuringService:
    """
    Create the structuring service.

    Note: it depends on the LLM provider — composition, not inheritance.
    """
    llm = get_llm_provider(settings)
    return LLMStructuringService(llm)
