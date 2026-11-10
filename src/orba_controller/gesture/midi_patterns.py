from __future__ import annotations

import math
from typing import Any

from orba_controller.core.events import Event
from orba_controller.gesture.profile import GestureComboRule, GestureMovementRule


class GestureComboMatcher:
    """Detect explicitly configured notes held together within a time window."""

    def __init__(self, rules: tuple[GestureComboRule, ...] = ()) -> None:
        self.rules = rules
        self._active_notes: dict[tuple[int, int], float] = {}
        self._fired: set[tuple[str, int]] = set()

    def process(self, message: dict[str, Any]) -> list[Event]:
        message_type = message.get("type")
        velocity = int(message.get("velocity") or 0)
        is_note_on = message_type == "note_on" and velocity > 0
        is_note_off = message_type == "note_off" or (
            message_type == "note_on" and velocity == 0
        )
        if not is_note_on and not is_note_off:
            return []

        channel = int(message.get("channel", 0))
        note = int(message.get("note", 0))
        event_time = message.get("elapsed_seconds")
        if (
            isinstance(event_time, bool)
            or not isinstance(event_time, (int, float))
            or not math.isfinite(event_time)
        ):
            return []

        note_key = (channel, note)
        if is_note_off:
            self._active_notes.pop(note_key, None)
            for rule in self.rules:
                if rule.channel in (None, channel) and not any(
                    (channel, combo_note) in self._active_notes for combo_note in rule.notes
                ):
                    self._fired.discard((rule.name, channel))
            return []

        self._active_notes.setdefault(note_key, float(event_time))
        matches: list[Event] = []
        for rule in self.rules:
            if rule.channel is not None and rule.channel != channel:
                continue
            fired_key = (rule.name, channel)
            if fired_key in self._fired:
                continue
            starts = [self._active_notes.get((channel, combo_note)) for combo_note in rule.notes]
            if any(start is None for start in starts):
                continue
            onset_spread = max(starts) - min(starts)
            if onset_spread > rule.max_gap_seconds:
                continue
            self._fired.add(fired_key)
            matches.append(Event(
                name="gesture.combo",
                payload={
                    "combo": rule.name,
                    "channel": channel,
                    "notes": list(rule.notes),
                    "onset_spread_seconds": round(onset_spread, 6),
                    "elapsed_seconds": round(float(event_time), 6),
                },
            ))
        return matches


class ControlMovementMatcher:
    """Detect thresholded changes on explicitly configured MIDI CC streams."""

    def __init__(self, rules: tuple[GestureMovementRule, ...] = ()) -> None:
        self.rules = rules
        self._previous: dict[tuple[int, int], tuple[int, float]] = {}
        self._last_emitted: dict[tuple[str, int], float] = {}

    def process(self, message: dict[str, Any]) -> list[Event]:
        if message.get("type") != "control_change":
            return []

        channel = int(message.get("channel", 0))
        control = message.get("control")
        value = message.get("value")
        event_time = message.get("elapsed_seconds")
        if (
            type(control) is not int
            or not 0 <= control <= 127
            or type(value) is not int
            or not 0 <= value <= 127
            or isinstance(event_time, bool)
            or not isinstance(event_time, (int, float))
            or not math.isfinite(event_time)
        ):
            return []

        stream_key = (channel, control)
        previous = self._previous.get(stream_key)
        self._previous[stream_key] = (value, float(event_time))
        if previous is None:
            return []

        previous_value, _ = previous
        delta = value - previous_value
        matches: list[Event] = []
        for rule in self.rules:
            if rule.control != control or rule.channel not in (None, channel):
                continue
            if abs(delta) < rule.min_delta:
                continue
            cooldown_key = (rule.name, channel)
            last_emitted = self._last_emitted.get(cooldown_key)
            if last_emitted is not None and event_time - last_emitted < rule.cooldown_seconds:
                continue
            self._last_emitted[cooldown_key] = float(event_time)
            matches.append(Event(
                name="gesture.move",
                payload={
                    "movement": rule.name,
                    "channel": channel,
                    "control": control,
                    "from_value": previous_value,
                    "to_value": value,
                    "delta": delta,
                    "direction": "up" if delta > 0 else "down",
                    "elapsed_seconds": round(float(event_time), 6),
                },
            ))
        return matches