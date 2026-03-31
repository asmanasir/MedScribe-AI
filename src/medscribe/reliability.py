from __future__ import annotations

"""
Reliability patterns for production healthcare systems.

1. RETRY — transient failures (network timeout, LLM overloaded)
2. FALLBACK — if primary LLM fails, try secondary
3. CIRCUIT BREAKER — stop calling a broken service, fail fast

These patterns are essential because:
- Ollama may run out of memory → retry after cooldown
- OpenAI may have API outages → fallback to local LLM
- Network issues → retry with exponential backoff
- Don't hammer a broken service → circuit breaker
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import wraps

import structlog

logger = structlog.get_logger()


# --- Retry ---

async def retry_async(
    fn: Callable,
    *args,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    retryable_exceptions: tuple = (Exception,),
    **kwargs,
):
    """
    Retry an async function with exponential backoff.

    Example:
        result = await retry_async(llm.generate, prompt, max_retries=3)
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as e:
            last_error = e
            if attempt < max_retries:
                wait = min(backoff_base * (2 ** attempt), backoff_max)
                logger.warning(
                    "reliability.retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    wait_seconds=wait,
                    error=str(e),
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "reliability.retry_exhausted",
                    attempts=max_retries + 1,
                    error=str(e),
                )
    raise last_error


def with_retry(max_retries: int = 3, backoff_base: float = 1.0):
    """Decorator version of retry."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await retry_async(fn, *args, max_retries=max_retries, backoff_base=backoff_base, **kwargs)
        return wrapper
    return decorator


# --- Fallback ---

async def with_fallback(primary_fn, fallback_fn, *args, **kwargs):
    """
    Try primary function, fall back to secondary on failure.

    Example:
        result = await with_fallback(openai_llm.generate, ollama_llm.generate, prompt)
    """
    try:
        return await primary_fn(*args, **kwargs)
    except Exception as primary_error:
        logger.warning(
            "reliability.fallback_triggered",
            primary_error=str(primary_error),
            fallback=fallback_fn.__qualname__,
        )
        return await fallback_fn(*args, **kwargs)


# --- Circuit Breaker ---

class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal — requests go through
    OPEN = "open"            # Broken — requests fail immediately
    HALF_OPEN = "half_open"  # Testing — one request allowed through


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern — stops calling a broken service.

    States:
      CLOSED → service healthy, requests pass through
      OPEN → service broken, requests fail immediately (no waiting)
      HALF_OPEN → testing if service recovered, one request allowed

    Example:
        breaker = CircuitBreaker(name="ollama", failure_threshold=3)
        result = await breaker.call(llm.generate, prompt)
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 30.0  # seconds before trying again
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    success_count: int = 0

    async def call(self, fn: Callable, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self.last_failure_time > self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("circuit_breaker.half_open", name=self.name)
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker '{self.name}' is OPEN. "
                    f"Service unavailable. Retry after {self.recovery_timeout}s."
                )

        try:
            result = await fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("circuit_breaker.recovered", name=self.name)
        self.success_count += 1

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(
                "circuit_breaker.opened",
                name=self.name,
                failures=self.failure_count,
            )

    @property
    def is_healthy(self) -> bool:
        return self.state == CircuitState.CLOSED


class CircuitBreakerOpenError(Exception):
    pass
