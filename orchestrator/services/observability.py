"""
orchestrator/services/observability.py
========================================
Structured logging, request context, latency tracking, and metrics.
Uses structlog for machine-parseable structured logs.
"""

import time
import functools
from contextvars import ContextVar
from typing import Any

import logging
import structlog

from orchestrator.config.settings import settings

# ── Request-scoped context ────────────────────────────────────
_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_session_id_var: ContextVar[str] = ContextVar("session_id", default="")


def set_request_id(rid: str) -> None:
    _request_id_var.set(rid)


def get_request_id() -> str:
    return _request_id_var.get("")


def set_session_id(sid: str) -> None:
    _session_id_var.set(sid)


def get_session_id() -> str:
    return _session_id_var.get("")


# ── Structlog Configuration ──────────────────────────────────

def _add_request_context(
    logger: Any, method_name: str, event_dict: dict
) -> dict:
    rid = _request_id_var.get("")
    sid = _session_id_var.get("")
    if rid:
        event_dict["request_id"] = rid
    if sid:
        event_dict["session_id"] = sid
    return event_dict


def configure_logging() -> None:
    """Configure structlog for the application."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer()
            if settings.debug
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Return a bound logger with the given name."""
    return structlog.get_logger(name)


# ── Latency Tracking Decorator ───────────────────────────────

def track_latency(metric_name: str):
    """Decorator that measures and logs execution time of async functions."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = (time.perf_counter() - start) * 1000
                metrics.record_latency(metric_name, elapsed)
                return result
            except Exception:
                elapsed = (time.perf_counter() - start) * 1000
                metrics.record_latency(f"{metric_name}_error", elapsed)
                raise
        return wrapper
    return decorator


# ── In-Memory Metrics ────────────────────────────────────────

class MetricsCollector:
    """Simple in-memory metrics for orchestrator observability."""

    def __init__(self):
        self._latencies: dict[str, list[float]] = {}
        self._counters: dict[str, int] = {}
        self._route_distribution: dict[str, int] = {}

    def record_latency(self, name: str, ms: float) -> None:
        self._latencies.setdefault(name, []).append(ms)
        # Keep only last 1000 measurements
        if len(self._latencies[name]) > 1000:
            self._latencies[name] = self._latencies[name][-500:]

    def increment(self, name: str, count: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + count

    def record_route(self, route: str) -> None:
        self._route_distribution[route] = self._route_distribution.get(route, 0) + 1

    def summary(self) -> dict:
        latency_summary = {}
        for name, values in self._latencies.items():
            if values:
                sorted_vals = sorted(values)
                latency_summary[name] = {
                    "count": len(sorted_vals),
                    "avg_ms": round(sum(sorted_vals) / len(sorted_vals), 2),
                    "p50_ms": round(sorted_vals[len(sorted_vals) // 2], 2),
                    "p95_ms": round(
                        sorted_vals[int(len(sorted_vals) * 0.95)], 2
                    ),
                    "max_ms": round(sorted_vals[-1], 2),
                }
        return {
            "latencies": latency_summary,
            "counters": dict(self._counters),
            "route_distribution": dict(self._route_distribution),
        }


# Module-level singleton
metrics = MetricsCollector()
