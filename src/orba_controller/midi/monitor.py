from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

try:
    import mido
    from mido import Message
except ImportError:  # pragma: no cover - dependency may be absent during startup
    mido = None
    Message = None


@dataclass(slots=True)
class PortInfo:
    name: str
    is_input: bool = True
    is_output: bool = False
    kind: str = "midi"


class MidiMonitor:
    """Small, safe MIDI monitor that exposes local port discovery and message handling."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._input = None
        self._port_name: str | None = None
        self.events: list[dict[str, Any]] = []
        self.last_error: str | None = None

    def list_input_names(self) -> list[str]:
        if self.dry_run or mido is None:
            return ["Mock Orba Input"] if self.dry_run else []
        try:
            names = list(mido.get_input_names())
            self.last_error = None
            return names
        except Exception as exc:  # noqa: BLE001 - CoreMIDI backend errors vary by macOS version.
            self.last_error = str(exc)
            return []

    def resolve_input_port(self, requested: str | None = None) -> str | None:
        names = self.list_input_names()
        if requested in names:
            return requested
        if requested and not any(token in requested.casefold() for token in ("orba", "artiphon")):
            return None

        candidates = [
            name for name in names
            if "orba" in name.casefold() or "artiphon" in name.casefold()
        ]
        virtual_ble = [
            name for name in candidates
            if "orba controller" in name.casefold() and ("ble" in name.casefold() or "bluetooth" in name.casefold())
        ]
        if virtual_ble:
            return virtual_ble[0]
        bluetooth = [
            name for name in candidates
            if "bluetooth" in name.casefold() or "ble" in name.casefold()
        ]
        if requested and any(token in requested.casefold() for token in ("bluetooth", "ble")):
            return bluetooth[0] if bluetooth else None
        return (bluetooth or candidates or (["Mock Orba Input"] if self.dry_run else []))[0] if (
            bluetooth or candidates or self.dry_run
        ) else None

    @property
    def connected_port(self) -> str | None:
        return self._port_name

    def list_ports(self) -> list[PortInfo]:
        if self.dry_run or mido is None:
            return [
                PortInfo(name="Mock Orba Input", is_input=True, is_output=False, kind="mock"),
                PortInfo(name="Mock Orba Output", is_input=False, is_output=True, kind="mock"),
            ]

        ports: list[PortInfo] = [
            PortInfo(name=name, is_input=True, is_output=False, kind="midi")
            for name in self.list_input_names()
        ]
        try:
            output_names = mido.get_output_names()
        except Exception as exc:  # noqa: BLE001 - CoreMIDI backend errors vary by macOS version.
            self.last_error = str(exc)
            output_names = []
        ports.extend(
            PortInfo(name=name, is_input=False, is_output=True, kind="midi")
            for name in output_names
        )
        return ports

    def connect(self, port_name: str | None = None) -> bool:
        if self.dry_run:
            self._input = object()
            self._port_name = port_name or "Mock Orba Input"
            self.last_error = None
            return True
        if mido is None:
            self.last_error = "mido is not available"
            return False
        try:
            selected_port = self.resolve_input_port(port_name)
            if selected_port is None:
                self.last_error = (
                    f"MIDI input port not found: {port_name}"
                    if port_name else "no Orba MIDI input ports are available"
                )
                return False
            self._input = mido.open_input(selected_port)
            self._port_name = selected_port
            self.last_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - RtMidi backend exceptions vary by platform.
            self._input = None
            self.last_error = str(exc)
            return False

    @property
    def connected(self) -> bool:
        return self._input is not None

    def is_input_available(self, port_name: str) -> bool:
        if mido is None:
            self.last_error = "mido is not available"
            return False
        try:
            available = port_name in mido.get_input_names()
        except Exception as exc:  # noqa: BLE001 - RtMidi backend exceptions vary by platform.
            self.last_error = str(exc)
            return False
        if available:
            self.last_error = None
        return available

    def close(self) -> None:
        input_port = self._input
        self._input = None
        self._port_name = None
        if input_port is not None and not self.dry_run:
            try:
                input_port.close()
            except Exception as exc:  # noqa: BLE001 - Port may already be gone after unplug.
                self.last_error = str(exc)

    def diagnose_ports(self) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        if mido is None:
            return diagnostics

        for port_name in mido.get_input_names():
            try:
                port = mido.open_input(port_name)
                port.close()
                diagnostics.append({"name": port_name, "type": "input", "openable": True})
            except Exception as exc:  # noqa: BLE001 - backend exceptions vary by platform.
                diagnostics.append({"name": port_name, "type": "input", "openable": False, "error": str(exc)})

        for port_name in mido.get_output_names():
            try:
                port = mido.open_output(port_name)
                port.close()
                diagnostics.append({"name": port_name, "type": "output", "openable": True})
            except Exception as exc:  # noqa: BLE001 - backend exceptions vary by platform.
                diagnostics.append({"name": port_name, "type": "output", "openable": False, "error": str(exc)})

        return diagnostics

    def read_messages(self, limit: int = 10) -> list[dict[str, Any]]:
        if self.dry_run:
            sample_messages = [
                {"type": "note_on", "note": 60, "velocity": 72, "channel": 0},
                {"type": "control_change", "control": 74, "value": 32, "channel": 0},
            ]
            current_events = sample_messages[:limit]
            self.events.extend(current_events)
            return current_events

        if self._input is None:
            return []

        self.last_error = None
        current_events: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                msg = self._input.receive(block=False)
            except Exception as exc:  # noqa: BLE001 - RtMidi read errors vary by platform.
                self.last_error = str(exc)
                break
            if msg is None:
                break
            current_events.append({
                "type": msg.type,
                "channel": getattr(msg, "channel", None),
                "note": getattr(msg, "note", None),
                "velocity": getattr(msg, "velocity", None),
                "control": getattr(msg, "control", None),
                "value": getattr(msg, "value", None),
                "program": getattr(msg, "program", None),
                "pitch": getattr(msg, "pitch", None),
                "pressure": getattr(msg, "pressure", None),
            })
        self.events.extend(current_events)
        return current_events

    def export_json(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.events, handle, indent=2)
        return path
