from __future__ import annotations

import math

from orba_controller.core.events import Event
from orba_controller.gesture.profile import GestureSequenceRule, GestureSequenceStep


class GestureSequenceMatcher:
    """Match ordered gesture steps against timestamped gesture events."""

    def __init__(self, rules: tuple[GestureSequenceRule, ...] = ()) -> None:
        self.rules = rules
        self._progress: dict[str, tuple[int, float, list[Event]]] = {}
        self._deferred: dict[int, tuple[Event, float]] = {}

    def process(self, event: Event) -> list[Event]:
        event_time = event.payload.get("elapsed_seconds")
        if (
            isinstance(event_time, bool)
            or not isinstance(event_time, (int, float))
            or not math.isfinite(event_time)
        ):
            return []

        elapsed = float(event_time)
        matched_sequences = self.flush_pending(elapsed)
        for rule in self.rules:
            progress, last_time, matched_steps = self._progress.get(rule.name, (0, 0.0, []))
            if progress and (elapsed < last_time or elapsed - last_time > rule.max_gap_seconds):
                progress, matched_steps = 0, []

            expected_step = rule.steps[progress] if progress < len(rule.steps) else None
            if expected_step is not None and self._matches(expected_step, event):
                matched_steps = [*matched_steps, event]
                progress += 1
                if progress == len(rule.steps):
                    first_time = float(matched_steps[0].payload["elapsed_seconds"])
                    matched_sequences.append(Event(
                        name="gesture.sequence",
                        payload={
                            "sequence": rule.name,
                            "steps": [step.name for step in matched_steps],
                            "elapsed_seconds": elapsed,
                            "duration_seconds": round(elapsed - first_time, 6),
                        },
                    ))
                    self._deferred.pop(id(matched_steps[0]), None)
                    self._progress.pop(rule.name, None)
                    continue
                self._progress[rule.name] = (progress, elapsed, matched_steps)
                if progress == 1:
                    prefix = matched_steps[0]
                    prefix_time = float(prefix.payload["elapsed_seconds"])
                    prefix_deadline = max(
                        prefix_time + candidate.max_gap_seconds
                        for candidate in self.rules
                        if self._matches(candidate.steps[0], prefix)
                    )
                    self._deferred[id(prefix)] = (prefix, prefix_deadline)
                continue

            if self._matches(rule.steps[0], event):
                self._progress[rule.name] = (1, elapsed, [event])
            else:
                self._progress.pop(rule.name, None)

        return matched_sequences

    def is_deferred(self, event: Event) -> bool:
        return id(event) in self._deferred

    def flush_pending(self, timestamp: float) -> list[Event]:
        expired: list[Event] = []
        for event_id, (event, deadline) in list(self._deferred.items()):
            if timestamp > deadline:
                expired.append(event)
                del self._deferred[event_id]
                for rule_name, (_, _, matched_steps) in list(self._progress.items()):
                    if matched_steps and matched_steps[0] is event:
                        del self._progress[rule_name]
        return expired

    @staticmethod
    def _matches(step: GestureSequenceStep, event: Event) -> bool:
        if event.name != f"gesture.{step.gesture}":
            return False
        if step.channel is not None and event.payload.get("channel") != step.channel:
            return False
        if step.note is not None and event.payload.get("note") != step.note:
            return False
        if step.pad is not None and event.payload.get("pad") != step.pad:
            return False
        return step.mode is None or event.payload.get("mode") == step.mode