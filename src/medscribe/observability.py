from __future__ import annotations

"""
Observability — tracing, metrics, structured logging.

Production healthcare systems need three pillars:
1. TRACES — follow a request across services (OpenTelemetry)
2. METRICS — measure latency, throughput, error rates (Prometheus)
3. LOGS — structured JSON logs with correlation IDs (structlog)

This module configures all three. Compatible with:
- Grafana LGTM stack (Loki, Grafana, Tempo, Mimir)
- Azure Monitor / Application Insights
- Any OpenTelemetry-compatible backend
"""

import time
from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

import structlog

# Request correlation ID — ties logs to a specific request
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(cid: str | None = None) -> str:
    cid = cid or str(uuid4())[:8]
    _correlation_id.set(cid)
    return cid


def configure_logging(json_output: bool = True):
    """Configure structured logging with correlation IDs."""
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_correlation_id,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_correlation_id(logger, method_name, event_dict):
    cid = get_correlation_id()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


class MetricsCollector:
    """
    Simple in-process metrics collector.

    Tracks:
    - Request counts per endpoint
    - Latency histograms per operation
    - Error counts per type
    - AI-specific metrics (tokens, confidence, model usage)

    In production, export to Prometheus/Grafana via OpenTelemetry.
    """

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._gauges: dict[str, float] = {}

    def increment(self, name: str, value: int = 1):
        self._counters[name] = self._counters.get(name, 0) + value

    def record_latency(self, name: str, ms: float):
        if name not in self._latencies:
            self._latencies[name] = []
        self._latencies[name].append(ms)
        # Keep only last 1000 entries
        if len(self._latencies[name]) > 1000:
            self._latencies[name] = self._latencies[name][-1000:]

    def set_gauge(self, name: str, value: float):
        self._gauges[name] = value

    def get_summary(self) -> dict:
        summary = {"counters": dict(self._counters), "gauges": dict(self._gauges)}
        latency_stats = {}
        for name, values in self._latencies.items():
            if values:
                sorted_v = sorted(values)
                latency_stats[name] = {
                    "count": len(values),
                    "avg_ms": round(sum(values) / len(values), 1),
                    "p50_ms": round(sorted_v[len(sorted_v) // 2], 1),
                    "p95_ms": round(sorted_v[int(len(sorted_v) * 0.95)], 1),
                    "p99_ms": round(sorted_v[int(len(sorted_v) * 0.99)], 1),
                }
        summary["latencies"] = latency_stats
        return summary


# Global metrics instance
metrics = MetricsCollector()


def track_latency(operation: str):
    """Decorator to track function execution latency."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
                metrics.increment(f"{operation}.success")
                return result
            except Exception:
                metrics.increment(f"{operation}.error")
                raise
            finally:
                elapsed_ms = (time.monotonic() - start) * 1000
                metrics.record_latency(operation, elapsed_ms)
        return wrapper
    return decorator
