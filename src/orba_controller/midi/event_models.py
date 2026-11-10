from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MidiEvent:
    type: str
    channel: int | None = None
    note: int | None = None
    velocity: int | None = None
    control: int | None = None
    value: int | None = None
    program: int | None = None
    pitch: int | None = None
    pressure: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type}
        if self.channel is not None:
            data["channel"] = self.channel
        if self.note is not None:
            data["note"] = self.note
        if self.velocity is not None:
            data["velocity"] = self.velocity
        if self.control is not None:
            data["control"] = self.control
        if self.value is not None:
            data["value"] = self.value
        if self.program is not None:
            data["program"] = self.program
        if self.pitch is not None:
            data["pitch"] = self.pitch
        if self.pressure is not None:
            data["pressure"] = self.pressure
        data["raw"] = self.raw
        return data


def parse_midi_message(message: dict[str, Any]) -> MidiEvent:
    """Normalize a MIDI payload into a portable structure."""
    msg_type = str(message.get("type", "unknown"))
    event = MidiEvent(type=msg_type, raw=dict(message))

    if msg_type in {"note_on", "note_off"}:
        event.channel = int(message.get("channel", 0))
        event.note = int(message.get("note", 0))
        event.velocity = int(message.get("velocity", 0))
    elif msg_type == "control_change":
        event.channel = int(message.get("channel", 0))
        event.control = int(message.get("control", 0))
        event.value = int(message.get("value", 0))
    elif msg_type == "program_change":
        event.channel = int(message.get("channel", 0))
        event.program = int(message.get("program", 0))
    elif msg_type == "pitchwheel":
        event.channel = int(message.get("channel", 0))
        event.pitch = int(message.get("pitch", 0))
    elif msg_type in {"pitch_bend", "aftertouch", "channel_pressure"}:
        event.channel = int(message.get("channel", 0))
        event.value = int(message.get("value", 0))
        if msg_type in {"aftertouch", "channel_pressure"}:
            event.pressure = int(message.get("pressure", message.get("value", 0)))

    return event
