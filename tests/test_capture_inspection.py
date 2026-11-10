import json

from orba_controller import main


def test_inspect_capture_summarizes_mode_and_motion_fields(tmp_path, capsys):
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(json.dumps({
        "events": [
            {"type": "program_change", "channel": 0, "program": 3},
            {"type": "note_on", "channel": 9, "note": 49},
            {"type": "control_change", "channel": 9, "control": 2, "value": 10},
            {"type": "control_change", "channel": 9, "control": 2, "value": 44},
            {"type": "pitchwheel", "channel": 9, "pitch": -100},
            {"type": "pitchwheel", "channel": 9, "pitch": 500},
            {"type": "aftertouch", "channel": 9, "pressure": 30},
        ]
    }), encoding="utf-8")

    result = main._inspect_capture(str(capture_path))

    output = capsys.readouterr().out
    assert result == 0
    assert "program 3" in output
    assert "CC2: min=10 max=44" in output
    assert "Pitchwheel ranges:" in output
    assert "min=-100 max=500" in output
    assert "Pressure ranges:" in output


def test_inspect_capture_warns_when_legacy_program_values_are_missing(tmp_path, capsys):
    capture_path = tmp_path / "legacy.json"
    capture_path.write_text(
        json.dumps({"events": [{"type": "program_change", "channel": 0}]}),
        encoding="utf-8",
    )

    result = main._inspect_capture(str(capture_path))

    assert result == 0
    assert "lack their program number" in capsys.readouterr().out