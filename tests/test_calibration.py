from __future__ import annotations

import json

from orba_controller.midi.calibration import CalibrationSession
from orba_controller.midi.monitor import MidiMonitor


def test_monitor_export_json_writes_snapshot(tmp_path):
    monitor = MidiMonitor(dry_run=True)
    monitor.events = [{"type": "note_on", "note": 60, "velocity": 80}]

    path = tmp_path / "snapshot.json"
    exported = monitor.export_json(str(path))

    assert exported == str(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[0]["note"] == 60


def test_calibration_session_tracks_capture():
    session = CalibrationSession(name="Orba 1 calibration")
    session.record_event({"type": "note_on", "note": 39, "velocity": 72, "channel": 0})
    session.record_event({"type": "control_change", "control": 74, "value": 31, "channel": 0})

    assert len(session.events) == 2
    assert session.events[0]["note"] == 39
    assert session.events[1]["control"] == 74
