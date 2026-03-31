"""
Ollama LLM provider — for running local models (Llama, Mistral, etc.).

Why have a local LLM option?
1. Data privacy — audio/text never leaves your network
2. Cost — no per-token billing
3. Norway/EU compliance — data stays in your jurisdiction
4. Development — works offline, no API key needed

Ollama exposes an OpenAI-compatible API, so the implementation
is similar to the OpenAI provider. But we keep them separate because:
- Different error handling (local vs. cloud)
- Different model naming conventions
- Different health check logic
"""

import time

import httpx
import structlog

from medscribe.config import Settings
from medscribe.services.base import LLMProvider, LLMResult

logger = structlog.get_logger()


class OllamaLLMProvider(LLMProvider):
    """Local LLM via Ollama."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ollama_base_url
        self._model = settings.ollama_model
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=120.0,  # Local models can be slow on first load
        )

    async def generate(self, prompt: str, system_prompt: str = "") -> LLMResult:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": 256,    # 256 tokens is enough for 7 JSON fields
                "num_ctx": 768,        # Minimal context = fastest on CPU
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        start = time.monotonic()
        response = await self._client.post("/api/generate", json=payload)
        response.raise_for_status()
        elapsed_ms = (time.monotonic() - start) * 1000

        data = response.json()

        logger.info(
            "llm.ollama.generated",
            model=self._model,
            elapsed_ms=round(elapsed_ms, 1),
        )

        return LLMResult(
            text=data.get("response", ""),
            model_id=f"ollama/{self._model}",
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            processing_time_ms=elapsed_ms,
        )

    async def health_check(self) -> bool:
        try:
            response = await self._client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            logger.warning("llm.ollama.health_check_failed")
            return False
