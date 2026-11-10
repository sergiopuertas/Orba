import json

from orba_controller import main
from orba_controller.gesture import PadModeMapper


def test_pad_map_capture_records_notes_per_mode(monkeypatch, tmp_path):
    class FakeMonitor:
        def __init__(self, dry_run):
            self.messages = [
                {"type": "note_on", "channel": 9, "note": 36, "velocity": 80},
                {"type": "note_on", "channel": 9, "note": 38, "velocity": 80},
                {"type": "note_on", "channel": 9, "note": 49, "velocity": 80},
                {"type": "note_on", "channel": 9, "note": 70, "velocity": 80},
                {"type": "note_on", "channel": 8, "note": 64, "velocity": 80},
                {"type": "note_on", "channel": 8, "note": 66, "velocity": 80},
                {"type": "note_on", "channel": 8, "note": 68, "velocity": 80},
                {"type": "note_on", "channel": 8, "note": 71, "velocity": 80},
            ]
            self.closed = False
            self.last_error = None

        def connect(self, port_name):
            return True

        def read_messages(self, limit):
            if not self.messages:
                return []
            message, self.messages = self.messages[0], self.messages[1:]
            return [message]

        def close(self):
            self.closed = True

    monitor = FakeMonitor(dry_run=False)
    monkeypatch.setattr(main, "MidiMonitor", lambda dry_run: monitor)
    output_path = tmp_path / "pad_map.json"

    result = main._learn_pad_map(
        "Orba MIDI",
        {"normal": 0, "teams": 1},
        [1, 2, 5, 8],
        str(output_path),
        input_fn=lambda prompt: "",
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert data["pads"]["normal"]["5"] == {"channel": 9, "note": 49}
    assert data["pads"]["teams"]["8"] == {"channel": 8, "note": 71}
    assert monitor.closed


def test_pad_map_capture_refuses_to_overwrite(tmp_path):
    output_path = tmp_path / "existing.json"
    output_path.write_text("{}", encoding="utf-8")

    result = main._learn_pad_map("Orba MIDI", {"normal": 0}, [5], str(output_path))

    assert result == 1
    assert output_path.read_text(encoding="utf-8") == "{}"


def test_pad_map_argument_parsers_validate_values():
    assert main._parse_mode_programs("normal=0,teams=1") == {"normal": 0, "teams": 1}
    assert main._parse_pad_numbers("1,2,5,8") == [1, 2, 5, 8]


def test_pad_mode_mapper_annotates_program_and_physical_pad(tmp_path):
    map_path = tmp_path / "pad_map.json"
    map_path.write_text(json.dumps({
        "mode_programs": {"normal": 0, "teams": 1},
        "pads": {
            "normal": {"5": {"channel": 9, "note": 43}},
            "teams": {"5": {"channel": 8, "note": 64}},
        },
    }), encoding="utf-8")
    mapper = PadModeMapper.load(map_path, initial_mode="normal")

    normal = mapper.annotate({"type": "note_on", "channel": 9, "note": 43})
    mapper.annotate({"type": "program_change", "program": 1})
    teams = mapper.annotate({"type": "note_on", "channel": 8, "note": 64})

    assert (normal["pad"], normal["mode"]) == (5, "normal")
    assert (teams["pad"], teams["mode"]) == (5, "teams")


def test_pad_map_capture_extends_base_without_losing_existing_pads(monkeypatch, tmp_path):
    base_path = tmp_path / "base.json"
    base_path.write_text(json.dumps({
        "mode_programs": {"normal": 0, "teams": 1},
        "pads": {
            "normal": {"5": {"channel": 9, "note": 49}},
            "teams": {"5": {"channel": 8, "note": 64}},
        },
    }), encoding="utf-8")

    class FakeMonitor:
        def __init__(self):
            self.messages = [
                {"type": "note_on", "channel": 9, "note": 45, "velocity": 80},
                {"type": "note_on", "channel": 8, "note": 66, "velocity": 80},
            ]

        def connect(self, port_name):
            return True

        def read_messages(self, limit):
            return [self.messages.pop(0)] if self.messages else []

        def close(self):
            pass

    monkeypatch.setattr(main, "MidiMonitor", lambda dry_run: FakeMonitor())
    output_path = tmp_path / "extended.json"

    result = main._learn_pad_map(
        "Orba MIDI",
        {"normal": 0, "teams": 1},
        [6],
        str(output_path),
        input_fn=lambda prompt: "",
        base_path=str(base_path),
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert data["pads"]["normal"]["5"] == {"channel": 9, "note": 49}
    assert data["pads"]["normal"]["6"] == {"channel": 9, "note": 45}
    assert data["pads"]["teams"]["5"] == {"channel": 8, "note": 64}
    assert data["pads"]["teams"]["6"] == {"channel": 8, "note": 66}