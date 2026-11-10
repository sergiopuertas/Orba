from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .events import Event


class EventBus:
    """Simple in-memory event bus for decoupled modules."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = {}

    def subscribe(self, event_name: str, callback: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_name, []).append(callback)

    def publish(self, event: Event) -> None:
        for callback in self._subscribers.get(event.name, []):
            callback(event)

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(name=event_name, payload=payload or {})
        self.publish(event)
        return event
