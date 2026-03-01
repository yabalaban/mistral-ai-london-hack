"""Global event bus for observability — broadcasts system events to dashboard clients."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SystemEvent:
    """A single event emitted from any conversation source."""

    type: str  # oracle_start, oracle, turn_change, message, grader, topic_set, summary, etc.
    conversation_id: str
    source: str  # "discord" or "web"
    source_label: str  # e.g. "#general" or "conv-abc123"
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "conversation_id": self.conversation_id,
            "source": self.source,
            "source_label": self.source_label,
            "data": self.data,
            "timestamp": self.timestamp,
        }


class EventBus:
    """Fan-out event bus — subscribers get an asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[SystemEvent]] = []

    def subscribe(self) -> asyncio.Queue[SystemEvent]:
        q: asyncio.Queue[SystemEvent] = asyncio.Queue(maxsize=200)
        self._subscribers.append(q)
        logger.info("EventBus: new subscriber (total=%d)", len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[SystemEvent]) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)
            logger.info("EventBus: subscriber removed (total=%d)", len(self._subscribers))

    def emit(self, event: SystemEvent) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to make room
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


# Module-level singleton
event_bus = EventBus()
