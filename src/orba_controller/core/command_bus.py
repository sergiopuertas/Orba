from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .event_bus import EventBus
from .events import Event

CommandHandler = Callable[[dict[str, Any]], dict[str, Any] | None]


class CommandBus:
    """Dispatch profile actions through an explicit, dry-run-first handler registry."""

    def __init__(self, *, dry_run: bool = True, event_bus: EventBus | None = None) -> None:
        self.dry_run = dry_run
        self.event_bus = event_bus
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, action: str, handler: CommandHandler) -> None:
        if not action:
            raise ValueError("action must be a non-empty string")
        if action in self._handlers:
            raise ValueError(f"A handler is already registered for action: {action}")
        self._handlers[action] = handler

    def dispatch(self, action_event: Event) -> Event:
        if action_event.name != "action.simulated":
            return self._publish(Event(
                name="command.rejected",
                payload={"reason": "unsupported_event", "event": action_event.name},
            ))

        action = action_event.payload.get("action")
        if not isinstance(action, str) or not action:
            return self._publish(Event(
                name="command.rejected",
                payload={"reason": "invalid_action", "event": action_event.as_dict()},
            ))

        if self.dry_run:
            return self._publish(Event(
                name="command.dry_run",
                payload={"action": action, "request": dict(action_event.payload)},
            ))

        handler = self._handlers.get(action)
        if handler is None:
            return self._publish(Event(
                name="command.rejected",
                payload={"action": action, "reason": "no_handler_registered"},
            ))

        try:
            result = handler(dict(action_event.payload))
        except Exception as exc:  # noqa: BLE001 - command handlers are extension boundaries.
            return self._publish(Event(
                name="command.failed",
                payload={"action": action, "error": str(exc)},
            ))

        if result is not None and not isinstance(result, dict):
            return self._publish(Event(
                name="command.failed",
                payload={"action": action, "error": "handler result must be a mapping or None"},
            ))

        return self._publish(Event(
            name="command.completed",
            payload={"action": action, "result": result or {}},
        ))

    def _publish(self, event: Event) -> Event:
        if self.event_bus is not None:
            self.event_bus.publish(event)
        return event