import json
from types import SimpleNamespace

from orba_controller import main
from orba_controller.midi.monitor import MidiMonitor


def test_read_messages_returns_only_the_current_batch():
    monitor = MidiMonitor(dry_run=True)

    first_batch = monitor.read_messages()
    second_batch = monitor.read_messages()

    assert len(first_batch) == 2
    assert second_batch == first_batch
    assert len(monitor.events) == 4


def test_read_messages_preserves_mode_pitch_and_pressure_fields():
    class FakeInput:
        def __init__(self):
            self.messages = [
                SimpleNamespace(type="program_change", channel=0, program=3),
                SimpleNamespace(type="pitchwheel", channel=9, pitch=-321),
                SimpleNamespace(type="aftertouch", channel=9, value=47),
            ]

        def receive(self, block=False):
            return self.messages.pop(0) if self.messages else None

    monitor = MidiMonitor(dry_run=False)
    monitor._input = FakeInput()

    messages = monitor.read_messages(limit=3)

    assert messages[0]["program"] == 3
    assert messages[1]["pitch"] == -321
    assert messages[2]["value"] == 47


def test_capture_does_not_fall_back_to_dry_run(monkeypatch, capsys):
    class UnavailableMonitor:
        def __init__(self, dry_run):
            self.last_error = "device busy"

        def connect(self, port):
            return False

    monkeypatch.setattr(main, "MidiMonitor", UnavailableMonitor)

    result = main._capture_calibration("Artiphon Orba MIDI", False, 1, None)

    assert result == 1
    assert "device busy" in capsys.readouterr().out


def test_capture_exports_elapsed_time_for_each_event(monkeypatch, tmp_path):
    class MessageMonitor:
        def __init__(self, dry_run):
            self.messages = [{"type": "note_on", "channel": 9, "note": 49, "velocity": 83}]

        def connect(self, port):
            return True

        def read_messages(self, limit):
            messages, self.messages = self.messages, []
            return messages

        def close(self):
            pass

    monkeypatch.setattr(main, "MidiMonitor", MessageMonitor)
    export_path = tmp_path / "capture.json"

    result = main._capture_calibration("Artiphon Orba MIDI", False, 0.1, str(export_path))

    events = json.loads(export_path.read_text())["events"]
    assert result == 0
    assert len(events) == 1
    assert events[0]["elapsed_seconds"] >= 0