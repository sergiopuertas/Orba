from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CalibrationSession:
    name: str
    events: list[dict[str, Any]] = field(default_factory=list)

    def record_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = dict(payload)
        self.events.append(event)
        return event

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "events": self.events}

    def export_json(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.as_dict(), handle, indent=2)
        return path
