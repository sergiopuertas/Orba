from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from orba_controller.core.events import Event


@dataclass(frozen=True, slots=True)
class GestureSequenceStep:
    gesture: str
    channel: int | None = None
    note: int | None = None
    pad: int | None = None
    mode: str | None = None


@dataclass(frozen=True, slots=True)
class GestureSequenceRule:
    name: str
    steps: tuple[GestureSequenceStep, ...]
    max_gap_seconds: float
    action: str


@dataclass(frozen=True, slots=True)
class GestureComboRule:
    name: str
    notes: tuple[int, ...]
    channel: int | None
    max_gap_seconds: float
    action: str


@dataclass(frozen=True, slots=True)
class GestureMovementRule:
    name: str
    control: int
    channel: int | None
    min_delta: int
    cooldown_seconds: float
    action: str


@dataclass(frozen=True, slots=True)
class PadActionBinding:
    gesture: str
    pad: int
    action: str
    mode: str | None = None


@dataclass(frozen=True, slots=True)
class GestureProfile:
    name: str
    description: str
    actions: dict[str, str]
    mode_actions: dict[str, str] = field(default_factory=dict)
    hold_threshold_seconds: float = 0.5
    double_tap_window_seconds: float = 0.3
    sequences: tuple[GestureSequenceRule, ...] = ()
    combos: tuple[GestureComboRule, ...] = ()
    movements: tuple[GestureMovementRule, ...] = ()
    bindings: tuple[PadActionBinding, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> GestureProfile:
        with Path(path).open(encoding="utf-8") as handle:
            data: Any = yaml.safe_load(handle)

        if not isinstance(data, dict) or not isinstance(data.get("profile"), dict):
            raise TypeError("Profile file must contain a profile mapping")

        profile_data = data["profile"]
        gesture_rules = profile_data.get("gestures", [])
        if not isinstance(gesture_rules, list):
            raise TypeError("profile.gestures must be a list")

        actions: dict[str, str] = {}
        for rule in gesture_rules:
            if not isinstance(rule, dict):
                raise TypeError("Each gesture rule must be a mapping")
            gesture_name = rule.get("name")
            action = rule.get("action")
            if not isinstance(gesture_name, str) or not isinstance(action, str):
                raise TypeError("Each gesture rule requires string name and action values")
            if gesture_name in actions:
                raise ValueError(f"Duplicate gesture rule: {gesture_name}")
            actions[gesture_name] = action

        raw_mode_actions = profile_data.get("mode_actions", {})
        if not isinstance(raw_mode_actions, dict) or any(
            not isinstance(mode, str) or not mode or not isinstance(action, str) or not action
            for mode, action in raw_mode_actions.items()
        ):
            raise TypeError("profile.mode_actions must map non-empty mode names to actions")
        mode_actions = dict(raw_mode_actions)

        engine_config = data.get("gesture_engine", {})
        if not isinstance(engine_config, dict):
            raise TypeError("gesture_engine must be a mapping")

        hold_threshold = float(engine_config.get("hold_threshold_seconds", 0.5))
        double_tap_window = float(engine_config.get("double_tap_window_seconds", 0.3))
        if hold_threshold <= 0 or double_tap_window < 0:
            raise ValueError("Gesture thresholds must be positive (double-tap may be zero)")

        sequence_rules = profile_data.get("sequences", [])
        if not isinstance(sequence_rules, list):
            raise TypeError("profile.sequences must be a list")

        sequences: list[GestureSequenceRule] = []
        sequence_names: set[str] = set()
        supported_gestures = {"tap", "hold", "double_tap"}
        for rule in sequence_rules:
            if not isinstance(rule, dict):
                raise TypeError("Each sequence rule must be a mapping")
            name = rule.get("name")
            action = rule.get("action")
            steps_data = rule.get("steps")
            if not isinstance(name, str) or not name:
                raise TypeError("Each sequence rule requires a non-empty name")
            if name in sequence_names:
                raise ValueError(f"Duplicate gesture sequence: {name}")
            if not isinstance(action, str):
                raise TypeError(f"Sequence {name} requires a string action")
            if not isinstance(steps_data, list) or len(steps_data) < 2:
                raise TypeError(f"Sequence {name} requires at least two steps")

            steps: list[GestureSequenceStep] = []
            for step_data in steps_data:
                if not isinstance(step_data, dict):
                    raise TypeError(f"Each step in sequence {name} must be a mapping")
                gesture = step_data.get("gesture")
                if gesture not in supported_gestures:
                    raise ValueError(f"Unsupported gesture in sequence {name}: {gesture}")
                channel = step_data.get("channel")
                note = step_data.get("note")
                pad = step_data.get("pad")
                mode = step_data.get("mode")
                if channel is not None and (type(channel) is not int or not 0 <= channel <= 15):
                    raise ValueError(f"Invalid MIDI channel in sequence {name}: {channel}")
                if note is not None and (type(note) is not int or not 0 <= note <= 127):
                    raise ValueError(f"Invalid MIDI note in sequence {name}: {note}")
                if pad is not None and (type(pad) is not int or not 1 <= pad <= 8):
                    raise ValueError(f"Invalid physical pad in sequence {name}: {pad}")
                if mode is not None and not isinstance(mode, str):
                    raise TypeError(f"Invalid mode in sequence {name}: {mode}")
                steps.append(GestureSequenceStep(gesture, channel, note, pad, mode))

            max_gap = float(rule.get("max_gap_seconds", 1.0))
            if not math.isfinite(max_gap) or max_gap <= 0:
                raise ValueError(f"Sequence {name} max_gap_seconds must be positive")
            sequences.append(GestureSequenceRule(name, tuple(steps), max_gap, action))
            sequence_names.add(name)

        combos_data = profile_data.get("combos", [])
        if not isinstance(combos_data, list):
            raise TypeError("profile.combos must be a list")
        combos: list[GestureComboRule] = []
        combo_names: set[str] = set()
        for rule in combos_data:
            if not isinstance(rule, dict):
                raise TypeError("Each combo rule must be a mapping")
            name, action, notes = rule.get("name"), rule.get("action"), rule.get("notes")
            if not isinstance(name, str) or not name:
                raise TypeError("Each combo rule requires a non-empty name")
            if name in combo_names:
                raise ValueError(f"Duplicate gesture combo: {name}")
            if not isinstance(action, str):
                raise TypeError(f"Combo {name} requires a string action")
            if (
                not isinstance(notes, list)
                or len(notes) < 2
                or any(type(note) is not int or not 0 <= note <= 127 for note in notes)
                or len(set(notes)) != len(notes)
            ):
                raise ValueError(f"Combo {name} requires at least two unique MIDI notes")
            channel = rule.get("channel")
            if channel is not None and (type(channel) is not int or not 0 <= channel <= 15):
                raise ValueError(f"Invalid MIDI channel in combo {name}: {channel}")
            max_gap = float(rule.get("max_gap_seconds", 0.15))
            if not math.isfinite(max_gap) or max_gap <= 0:
                raise ValueError(f"Combo {name} max_gap_seconds must be positive")
            combos.append(GestureComboRule(name, tuple(sorted(notes)), channel, max_gap, action))
            combo_names.add(name)

        movements_data = profile_data.get("movements", [])
        if not isinstance(movements_data, list):
            raise TypeError("profile.movements must be a list")
        movements: list[GestureMovementRule] = []
        movement_names: set[str] = set()
        for rule in movements_data:
            if not isinstance(rule, dict):
                raise TypeError("Each movement rule must be a mapping")
            name, action = rule.get("name"), rule.get("action")
            control = rule.get("control")
            min_delta = rule.get("min_delta")
            if not isinstance(name, str) or not name:
                raise TypeError("Each movement rule requires a non-empty name")
            if name in movement_names:
                raise ValueError(f"Duplicate movement rule: {name}")
            if not isinstance(action, str):
                raise TypeError(f"Movement {name} requires a string action")
            if type(control) is not int or not 0 <= control <= 127:
                raise ValueError(f"Invalid MIDI control in movement {name}: {control}")
            if type(min_delta) is not int or not 1 <= min_delta <= 127:
                raise ValueError(f"Movement {name} min_delta must be between 1 and 127")
            channel = rule.get("channel")
            if channel is not None and (type(channel) is not int or not 0 <= channel <= 15):
                raise ValueError(f"Invalid MIDI channel in movement {name}: {channel}")
            cooldown = float(rule.get("cooldown_seconds", 0.15))
            if not math.isfinite(cooldown) or cooldown < 0:
                raise ValueError(f"Movement {name} cooldown_seconds cannot be negative")
            movements.append(
                GestureMovementRule(name, control, channel, min_delta, cooldown, action)
            )
            movement_names.add(name)

        bindings_data = profile_data.get("bindings", [])
        if not isinstance(bindings_data, list):
            raise TypeError("profile.bindings must be a list")
        bindings: list[PadActionBinding] = []
        binding_keys: set[tuple[str, int, str | None]] = set()
        for rule in bindings_data:
            if not isinstance(rule, dict):
                raise TypeError("Each pad binding must be a mapping")
            gesture, pad, action, mode = (
                rule.get("gesture"), rule.get("pad"), rule.get("action"), rule.get("mode")
            )
            if gesture not in {"tap", "hold", "double_tap"}:
                raise ValueError(f"Unsupported gesture in pad binding: {gesture}")
            if type(pad) is not int or not 1 <= pad <= 8:
                raise ValueError(f"Invalid physical pad in binding: {pad}")
            if not isinstance(action, str) or not action:
                raise TypeError("Each pad binding requires a non-empty action")
            if mode is not None and (not isinstance(mode, str) or not mode):
                raise TypeError("Binding mode must be a non-empty string or null")
            key = (gesture, pad, mode)
            if key in binding_keys:
                raise ValueError(f"Duplicate pad binding: {key}")
            bindings.append(PadActionBinding(gesture, pad, action, mode))
            binding_keys.add(key)

        return cls(
            name=str(profile_data.get("name", "Unnamed")),
            description=str(profile_data.get("description", "")),
            actions=actions,
            mode_actions=mode_actions,
            hold_threshold_seconds=hold_threshold,
            double_tap_window_seconds=double_tap_window,
            sequences=tuple(sequences),
            combos=tuple(combos),
            movements=tuple(movements),
            bindings=tuple(bindings),
        )

    def map_gesture(self, event: Event) -> Event | None:
        if event.name == "mode.changed":
            mode = event.payload.get("mode")
            action = self.mode_actions.get(mode) if isinstance(mode, str) else None
            if action is None:
                return None
            return Event(
                name="action.simulated",
                payload={
                    "profile": self.name,
                    "gesture": event.name,
                    "action": action,
                    "mode": mode,
                    "gesture_payload": event.payload,
                },
            )

        if event.name.startswith("gesture."):
            gesture_name = event.name.removeprefix("gesture.")
            event_pad, event_mode = event.payload.get("pad"), event.payload.get("mode")
            matched_binding = next((
                binding for binding in self.bindings
                if binding.gesture == gesture_name
                and binding.pad == event_pad
                and binding.mode == event_mode
            ), None)
            if matched_binding is None:
                matched_binding = next((
                    binding for binding in self.bindings
                    if binding.gesture == gesture_name
                    and binding.pad == event_pad
                    and binding.mode is None
                ), None)
            if matched_binding is not None:
                return Event(
                    name="action.simulated",
                    payload={
                        "profile": self.name,
                        "gesture": event.name,
                        "action": matched_binding.action,
                        "gesture_payload": event.payload,
                    },
                )

        if event.name == "gesture.sequence":
            sequence_name = event.payload.get("sequence")
            sequence = next((rule for rule in self.sequences if rule.name == sequence_name), None)
            if sequence is None:
                return None
            action = sequence.action
        elif event.name == "gesture.combo":
            combo_name = event.payload.get("combo")
            combo = next((rule for rule in self.combos if rule.name == combo_name), None)
            if combo is None:
                return None
            action = combo.action
        elif event.name == "gesture.move":
            movement_name = event.payload.get("movement")
            movement = next(
                (rule for rule in self.movements if rule.name == movement_name), None
            )
            if movement is None:
                return None
            action = movement.action
        else:
            if not event.name.startswith("gesture."):
                return None
            gesture_name = event.name.removeprefix("gesture.")
            action = self.actions.get(gesture_name)

        if action is None:
            return None

        return Event(
            name="action.simulated",
            payload={
                "profile": self.name,
                "gesture": event.name,
                "action": action,
                "gesture_payload": event.payload,
            },
        )