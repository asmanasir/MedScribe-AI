"""
OpenAI LLM provider implementation.

This is one concrete strategy for the LLMProvider interface.
It wraps the OpenAI SDK and maps responses to our domain types.
"""

import time

import structlog
from openai import AsyncOpenAI

from medscribe.config import Settings
from medscribe.services.base import LLMProvider, LLMResult

logger = structlog.get_logger()


class OpenAILLMProvider(LLMProvider):
    """
    OpenAI-backed LLM provider (GPT-4o, etc.).

    Note: We use AsyncOpenAI — the async client. This is critical
    for a FastAPI app because FastAPI is async. Using the sync client
    would block the event loop and tank your throughput.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
        )
        self._model = settings.openai_model

    async def generate(self, prompt: str, system_prompt: str = "") -> LLMResult:
        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,  # Low temp for medical accuracy
            max_tokens=4096,
        )
        elapsed_ms = (time.monotonic() - start) * 1000

        choice = response.choices[0]
        usage = response.usage

        logger.info(
            "llm.openai.generated",
            model=self._model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return LLMResult(
            text=choice.message.content or "",
            model_id=f"openai/{self._model}",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            processing_time_ms=elapsed_ms,
        )

    async def health_check(self) -> bool:
        try:
            # Cheap call to verify connectivity
            await self._client.models.list()
            return True
        except Exception:
            logger.warning("llm.openai.health_check_failed")
            return False
