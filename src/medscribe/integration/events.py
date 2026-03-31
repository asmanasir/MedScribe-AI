from __future__ import annotations

"""
Event system — decouples your service from consumers.

When a visit is approved, multiple things might need to happen:
- Notify Aidn
- Send to the EPJ system
- Trigger a webhook
- Log to analytics

Instead of calling each one directly (tight coupling), you emit events.
Handlers subscribe to events. New integrations = new handlers, zero code
changes to existing logic.

This is an IN-PROCESS event bus. For production scale:
- Replace with Kafka, RabbitMQ, or Azure Service Bus
- The interface stays the same (emit events, handle events)
- That's the point of the abstraction

Pattern: Observer / Pub-Sub
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger()

# Type alias for event handlers
EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """Base event — all events have these fields."""

    event_type: str
    visit_id: UUID | None = None
    data: dict = field(default_factory=dict)
    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """
    In-process async event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("visit.approved", my_handler)
        await bus.emit(Event(event_type="visit.approved", data={...}))

    Handlers run concurrently (asyncio.gather).
    If a handler fails, it's logged but doesn't block others.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)
        logger.info("event_bus.subscribed", event_type=event_type, handler=handler.__name__)

    async def emit(self, event: Event) -> None:
        """Emit an event to all subscribed handlers."""
        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            return

        logger.info(
            "event_bus.emitting",
            event_type=event.event_type,
            handler_count=len(handlers),
            event_id=str(event.event_id),
        )

        # Run handlers concurrently — one failing doesn't block others
        results = await asyncio.gather(
            *[self._safe_call(h, event) for h in handlers],
            return_exceptions=True,
        )

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "event_bus.handler_failed",
                    handler=handlers[i].__name__,
                    event_type=event.event_type,
                    error=str(result),
                )

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Call a handler with error isolation."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(
                "event_bus.handler_error",
                handler=handler.__name__,
                error=str(e),
            )
            raise


# Standard event types — use these constants, not raw strings
class EventTypes:
    VISIT_CREATED = "visit.created"
    TRANSCRIPTION_COMPLETED = "transcription.completed"
    STRUCTURING_COMPLETED = "structuring.completed"
    NOTE_APPROVED = "visit.approved"
    NOTE_REJECTED = "visit.rejected"
    SAFETY_FLAG_RAISED = "safety.flag_raised"
