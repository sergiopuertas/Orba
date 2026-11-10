from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PadModeMapper:
    """Annotate raw MIDI messages with the active mode and physical pad number."""

    def __init__(
        self,
        mode_programs: dict[str, int],
        pads: dict[str, dict[str, dict[str, int]]],
        initial_mode: str | None = None,
    ) -> None:
        self.mode_programs = dict(mode_programs)
        self.pads = pads
        self._program_modes = {program: mode for mode, program in mode_programs.items()}
        if initial_mode is not None and initial_mode not in self.mode_programs:
            raise ValueError(f"Unknown initial mode: {initial_mode}")
        self.current_mode = initial_mode

    @classmethod
    def load(cls, path: str | Path, initial_mode: str | None = None) -> PadModeMapper:
        data: Any = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("Pad map must contain a JSON object")
        raw_modes, raw_pads = data.get("mode_programs"), data.get("pads")
        if not isinstance(raw_modes, dict) or not isinstance(raw_pads, dict):
            raise TypeError("Pad map requires mode_programs and pads objects")

        mode_programs: dict[str, int] = {}
        for mode, program in raw_modes.items():
            if not isinstance(mode, str) or type(program) is not int or not 0 <= program <= 127:
                raise ValueError("Pad map mode programs must map names to MIDI program numbers")
            if program in mode_programs.values():
                raise ValueError(f"Duplicate MIDI program in pad map: {program}")
            mode_programs[mode] = program

        pads: dict[str, dict[str, dict[str, int]]] = {}
        for mode, mode_pads in raw_pads.items():
            if mode not in mode_programs or not isinstance(mode_pads, dict):
                raise ValueError(f"Pad mappings refer to an unknown or invalid mode: {mode}")
            pads[mode] = {}
            seen_notes: set[tuple[int, int]] = set()
            for pad, mapping in mode_pads.items():
                if not pad.isdigit() or not 1 <= int(pad) <= 8 or not isinstance(mapping, dict):
                    raise ValueError(f"Invalid pad entry in mode {mode}: {pad}")
                channel, note = mapping.get("channel"), mapping.get("note")
                if (
                    type(channel) is not int or not 0 <= channel <= 15
                    or type(note) is not int or not 0 <= note <= 127
                ):
                    raise ValueError(f"Invalid MIDI channel/note for pad {pad} in mode {mode}")
                if (channel, note) in seen_notes:
                    raise ValueError(f"Duplicate MIDI note {note} on channel {channel} in mode {mode}")
                seen_notes.add((channel, note))
                pads[mode][pad] = {"channel": channel, "note": note}

        return cls(mode_programs, pads, initial_mode)

    def annotate(self, message: dict[str, Any]) -> dict[str, Any]:
        annotated = dict(message)
        if message.get("type") == "program_change":
            program = message.get("program")
            if type(program) is int:
                self.current_mode = self._program_modes.get(program, f"program_{program}")
            if self.current_mode is not None:
                annotated["mode"] = self.current_mode
            return annotated

        if self.current_mode is not None:
            annotated["mode"] = self.current_mode
            mapping = self.pads.get(self.current_mode, {})
            for pad_number, pad_mapping in mapping.items():
                if (
                    message.get("channel") == pad_mapping["channel"]
                    and message.get("note") == pad_mapping["note"]
                ):
                    annotated["pad"] = int(pad_number)
                    break
            return annotated

        candidate_pads = {
            int(pad_number)
            for mode_pads in self.pads.values()
            for pad_number, pad_mapping in mode_pads.items()
            if message.get("channel") == pad_mapping["channel"]
            and message.get("note") == pad_mapping["note"]
        }
        if len(candidate_pads) == 1:
            annotated["pad"] = candidate_pads.pop()
        return annotated