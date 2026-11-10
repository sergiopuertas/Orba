from __future__ import annotations

import time
from typing import Any

from orba_controller.core.event_bus import EventBus
from orba_controller.core.events import Event


class GestureEngine:
    """Recognize generic note gestures without assuming Orba-specific mappings."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        hold_threshold_seconds: float = 0.5,
        double_tap_window_seconds: float = 0.3,
    ) -> None:
        if hold_threshold_seconds <= 0:
            raise ValueError("hold_threshold_seconds must be positive")
        if double_tap_window_seconds < 0:
            raise ValueError("double_tap_window_seconds cannot be negative")

        self.event_bus = event_bus
        self.hold_threshold_seconds = hold_threshold_seconds
        self.double_tap_window_seconds = double_tap_window_seconds
        self._active_notes: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
        self._pending_taps: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}

    def process(
        self,
        message: dict[str, Any],
        timestamp: float | None = None,
    ) -> list[Event]:
        event_time = self._event_time(message, timestamp)
        events = self._flush_expired_taps(event_time)
        message_type = message.get("type")
        velocity = int(message.get("velocity") or 0)
        is_note_on = message_type == "note_on" and velocity > 0
        is_note_off = message_type == "note_off" or (message_type == "note_on" and velocity == 0)
        if not is_note_on and not is_note_off:
            self._publish(events)
            return events

        channel = int(message.get("channel", 0))
        note = int(message.get("note", 0))
        note_key = (channel, note)

        if is_note_on:
            note_context = {
                key: message[key]
                for key in ("pad", "mode")
                if key in message
            }
            self._active_notes[note_key] = (event_time, note_context)
            self._publish(events)
            return events

        note_state = self._active_notes.pop(note_key, None)
        if note_state is None:
            self._publish(events)
            return events

        note_started, note_context = note_state
        duration = max(0.0, event_time - note_started)
        gesture_name = "hold" if duration >= self.hold_threshold_seconds else "tap"
        payload = {
            "channel": channel,
            "note": note,
            "duration_seconds": round(duration, 6),
            "elapsed_seconds": round(event_time, 6),
            **note_context,
        }

        if gesture_name == "tap":
            previous_tap = self._pending_taps.pop(note_key, None)
            if previous_tap is not None:
                previous_time, _ = previous_tap
                interval = event_time - previous_time
                events.append(Event(
                    name="gesture.double_tap",
                    payload={**payload, "tap_count": 2, "interval_seconds": round(interval, 6)},
                ))
            else:
                self._pending_taps[note_key] = (event_time, payload)
        else:
            pending_tap = self._pending_taps.pop(note_key, None)
            if pending_tap is not None:
                events.append(Event(name="gesture.tap", payload=pending_tap[1]))
            events.append(Event(name="gesture.hold", payload=payload))

        self._publish(events)
        return events

    def flush_pending(self, timestamp: float | None = None) -> list[Event]:
        """Emit single taps whose double-tap window has elapsed, including while idle."""
        event_time = time.monotonic() if timestamp is None else float(timestamp)
        events = self._flush_expired_taps(event_time)
        self._publish(events)
        return events

    def _flush_expired_taps(self, event_time: float) -> list[Event]:
        events: list[Event] = []
        for note_key, (tap_time, payload) in list(self._pending_taps.items()):
            if event_time - tap_time > self.double_tap_window_seconds:
                events.append(Event(name="gesture.tap", payload=payload))
                del self._pending_taps[note_key]
        return events

    def _publish(self, events: list[Event]) -> None:
        if self.event_bus is not None:
            for event in events:
                self.event_bus.publish(event)

    @staticmethod
    def _event_time(message: dict[str, Any], timestamp: float | None) -> float:
        if timestamp is not None:
            return float(timestamp)
        if "elapsed_seconds" in message:
            return float(message["elapsed_seconds"])
        return time.monotonic()