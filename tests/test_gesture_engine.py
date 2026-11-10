import pytest

from orba_controller import main
from orba_controller.core.event_bus import EventBus
from orba_controller.core.events import Event
from orba_controller.gesture import (
    ControlMovementMatcher,
    GestureComboMatcher,
    GestureComboRule,
    GestureEngine,
    GestureMovementRule,
    GestureSequenceMatcher,
    GestureSequenceRule,
    GestureSequenceStep,
)


def note_message(message_type, note=49, channel=9, velocity=80):
    return {
        "type": message_type,
        "note": note,
        "channel": channel,
        "velocity": velocity,
    }


def test_short_note_emits_tap_with_note_and_duration():
    engine = GestureEngine()

    assert engine.process(note_message("note_on"), timestamp=1.0) == []
    assert engine.process(note_message("note_off", velocity=30), timestamp=1.12) == []
    events = engine.flush_pending(timestamp=1.421)

    assert [event.name for event in events] == ["gesture.tap"]
    assert events[0].payload == {
        "channel": 9,
        "note": 49,
        "duration_seconds": 0.12,
        "elapsed_seconds": 1.12,
    }


def test_note_gesture_preserves_physical_pad_and_mode_context():
    engine = GestureEngine(double_tap_window_seconds=0.1)

    engine.process({**note_message("note_on"), "pad": 5, "mode": "normal"}, timestamp=1.0)
    engine.process({**note_message("note_off"), "pad": 5, "mode": "normal"}, timestamp=1.05)
    events = engine.flush_pending(timestamp=1.151)

    assert events[0].payload["pad"] == 5
    assert events[0].payload["mode"] == "normal"


def test_long_note_emits_hold():
    engine = GestureEngine(hold_threshold_seconds=0.5)

    engine.process(note_message("note_on"), timestamp=2.0)
    events = engine.process(note_message("note_off"), timestamp=2.5)

    assert [event.name for event in events] == ["gesture.hold"]


def test_two_short_notes_emit_double_tap():
    engine = GestureEngine(double_tap_window_seconds=0.3)

    engine.process(note_message("note_on"), timestamp=0.0)
    first_tap = engine.process(note_message("note_off"), timestamp=0.05)
    engine.process(note_message("note_on"), timestamp=0.2)
    second_tap = engine.process(note_message("note_off"), timestamp=0.25)

    assert first_tap == []
    assert [event.name for event in second_tap] == ["gesture.double_tap"]
    assert second_tap[0].payload["interval_seconds"] == 0.2


def test_zero_velocity_note_on_closes_note_and_bus_publishes_gestures():
    bus = EventBus()
    seen = []
    bus.subscribe("gesture.tap", seen.append)
    engine = GestureEngine(event_bus=bus)

    engine.process(note_message("note_on"), timestamp=1.0)
    engine.process(note_message("note_on", velocity=0), timestamp=1.1)
    events = engine.flush_pending(timestamp=1.401)

    assert [event.name for event in events] == ["gesture.tap"]
    assert seen == events


def test_different_notes_do_not_form_a_double_tap():
    engine = GestureEngine()

    engine.process(note_message("note_on", note=49), timestamp=0.0)
    engine.process(note_message("note_off", note=49), timestamp=0.05)
    engine.process(note_message("note_on", note=43), timestamp=0.1)
    engine.process(note_message("note_off", note=43), timestamp=0.15)
    events = engine.flush_pending(timestamp=0.451)

    assert [event.name for event in events] == ["gesture.tap", "gesture.tap"]


def test_sequence_matches_steps_within_time_window_and_note_filters():
    rule = GestureSequenceRule(
        name="tap_then_hold",
        steps=(
            GestureSequenceStep("tap", channel=9, note=49),
            GestureSequenceStep("hold", channel=9, note=43),
        ),
        max_gap_seconds=1.0,
        action="safe_ack",
    )
    matcher = GestureSequenceMatcher((rule,))

    assert matcher.process(Event("gesture.tap", {
        "channel": 9, "note": 49, "elapsed_seconds": 1.0,
    })) == []
    events = matcher.process(Event("gesture.hold", {
        "channel": 9, "note": 43, "elapsed_seconds": 1.75,
    }))

    assert [event.name for event in events] == ["gesture.sequence"]
    assert events[0].payload["sequence"] == "tap_then_hold"
    assert events[0].payload["duration_seconds"] == 0.75
    assert matcher.flush_pending(2.0) == []


def test_sequence_defers_prefix_tap_but_suppresses_it_when_swipe_completes():
    rule = GestureSequenceRule(
        name="pad_swipe",
        steps=(
            GestureSequenceStep("tap", pad=5, mode="normal"),
            GestureSequenceStep("tap", pad=6, mode="normal"),
        ),
        max_gap_seconds=0.4,
        action="spotify.next",
    )
    matcher = GestureSequenceMatcher((rule,))
    first_tap = Event("gesture.tap", {
        "pad": 5, "mode": "normal", "elapsed_seconds": 1.0,
    })

    assert matcher.process(first_tap) == []
    assert matcher.is_deferred(first_tap)
    swipe = matcher.process(Event("gesture.tap", {
        "pad": 6, "mode": "normal", "elapsed_seconds": 1.2,
    }))

    assert [event.name for event in swipe] == ["gesture.sequence"]
    assert swipe[0].payload["sequence"] == "pad_swipe"
    assert not matcher.is_deferred(first_tap)


def test_swipe_sequence_can_filter_by_physical_pad_and_mode():
    rule = GestureSequenceRule(
        name="spotify_next",
        steps=(
            GestureSequenceStep("tap", pad=5, mode="mode2"),
            GestureSequenceStep("tap", pad=6, mode="mode2"),
        ),
        max_gap_seconds=0.5,
        action="spotify.next",
    )
    matcher = GestureSequenceMatcher((rule,))

    assert matcher.process(Event("gesture.tap", {
        "pad": 5, "mode": "mode2", "elapsed_seconds": 0.0,
    })) == []
    matched = matcher.process(Event("gesture.tap", {
        "pad": 6, "mode": "mode2", "elapsed_seconds": 0.2,
    }))

    assert [event.name for event in matched] == ["gesture.sequence"]
    assert matched[0].payload["sequence"] == "spotify_next"


def test_sequence_prefix_falls_back_to_single_tap_when_no_swipe_follows():
    rule = GestureSequenceRule(
        name="pad_swipe",
        steps=(GestureSequenceStep("tap", pad=5), GestureSequenceStep("tap", pad=6)),
        max_gap_seconds=0.4,
        action="spotify.next",
    )
    matcher = GestureSequenceMatcher((rule,))
    first_tap = Event("gesture.tap", {"pad": 5, "elapsed_seconds": 1.0})

    assert matcher.process(first_tap) == []
    assert matcher.flush_pending(1.401) == [first_tap]
    assert not matcher.is_deferred(first_tap)


def test_sequence_resets_when_gap_exceeds_limit():
    rule = GestureSequenceRule(
        name="tap_then_hold",
        steps=(GestureSequenceStep("tap"), GestureSequenceStep("hold")),
        max_gap_seconds=1.0,
        action="noop",
    )
    matcher = GestureSequenceMatcher((rule,))

    matcher.process(Event("gesture.tap", {"elapsed_seconds": 0.0}))
    expired = matcher.process(Event("gesture.hold", {"elapsed_seconds": 1.1}))
    assert [event.name for event in expired] == ["gesture.tap"]
    matcher.process(Event("gesture.tap", {"elapsed_seconds": 1.2}))
    events = matcher.process(Event("gesture.hold", {"elapsed_seconds": 2.0}))

    assert [event.name for event in events] == ["gesture.sequence"]


def test_combo_emits_once_until_all_notes_are_released():
    rule = GestureComboRule("observed_overlap", (38, 42), 9, 0.15, "noop")
    matcher = GestureComboMatcher((rule,))

    def timed_note(message_type, note, timestamp):
        return {**note_message(message_type, note=note, channel=9), "elapsed_seconds": timestamp}

    assert matcher.process(timed_note("note_on", 38, 1.0)) == []
    combo = matcher.process(timed_note("note_on", 42, 1.08))

    assert [event.name for event in combo] == ["gesture.combo"]
    assert combo[0].payload["notes"] == [38, 42]
    assert matcher.process(timed_note("note_on", 42, 1.1)) == []
    matcher.process(timed_note("note_off", 38, 1.12))
    assert matcher.process(timed_note("note_on", 38, 1.14)) == []
    matcher.process(timed_note("note_off", 42, 1.2))
    matcher.process(timed_note("note_off", 38, 1.25))

    assert matcher.process(timed_note("note_on", 42, 2.0)) == []
    combo = matcher.process(timed_note("note_on", 38, 2.05))
    assert [event.name for event in combo] == ["gesture.combo"]


def test_control_movement_obeys_delta_threshold_and_cooldown():
    rule = GestureMovementRule("cc2_change", 2, 9, 10, 0.2, "noop")
    matcher = ControlMovementMatcher((rule,))

    def control(value, timestamp):
        return matcher.process({
            "type": "control_change",
            "channel": 9,
            "control": 2,
            "value": value,
            "elapsed_seconds": timestamp,
        })

    assert control(10, 0.0) == []
    first = control(20, 0.01)
    assert [event.name for event in first] == ["gesture.move"]
    assert first[0].payload["direction"] == "up"
    assert control(25, 0.1) == []
    assert control(35, 0.15) == []
    second = control(25, 0.25)
    assert [event.name for event in second] == ["gesture.move"]
    assert second[0].payload["direction"] == "down"


def test_live_gesture_monitor_recognizes_notes_and_closes_port(monkeypatch, capsys):
    class MessageMonitor:
        def __init__(self, dry_run):
            self.messages = [
                note_message("note_on"),
                note_message("note_off"),
            ]
            self.closed = False
            self.connected = False
            self.last_error = None

        def is_input_available(self, port):
            return True

        def connect(self, port):
            self.connected = True
            return True

        def read_messages(self, limit):
            if self.messages:
                return [self.messages.pop(0)]
            return []

        def close(self):
            self.closed = True
            self.connected = False

    monitor = MessageMonitor(dry_run=False)
    monkeypatch.setattr(main, "MidiMonitor", lambda dry_run: monitor)

    result = main._monitor_gestures("Artiphon Orba MIDI", 0.1, simulate_actions=True)

    assert result == 0
    assert monitor.closed
    output = capsys.readouterr().out
    assert "GESTURE {'name': 'gesture.tap'" in output
    assert "SIMULATED {'name': 'action.simulated'" in output
    assert "COMMAND {'name': 'command.dry_run'" in output


def test_gesture_monitor_reconnects_after_input_disappears(monkeypatch, capsys):
    class ReconnectingMonitor:
        def __init__(self, dry_run):
            self.availability = [True, False, True]
            self.messages = [note_message("note_on"), note_message("note_off")]
            self.connected = False
            self.connect_count = 0
            self.close_count = 0
            self.last_error = None

        def is_input_available(self, port):
            if self.availability:
                return self.availability.pop(0)
            return True

        def connect(self, port):
            self.connect_count += 1
            self.connected = True
            return True

        def read_messages(self, limit):
            messages, self.messages = self.messages, []
            return messages

        def close(self):
            self.connected = False
            self.close_count += 1

    monitor = ReconnectingMonitor(dry_run=False)
    monkeypatch.setattr(main, "MidiMonitor", lambda dry_run: monitor)

    result = main._monitor_gestures(
        "Artiphon Orba MIDI",
        0.15,
        reconnect_interval_seconds=0.01,
    )

    assert result == 0
    assert monitor.connect_count == 2
    assert monitor.close_count == 2
    assert "MIDI input disconnected" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("hold_threshold", "double_tap_window"),
    [(0, 0.3), (0.5, -0.1)],
)
def test_invalid_thresholds_are_rejected(hold_threshold, double_tap_window):
    with pytest.raises(ValueError):
        GestureEngine(
            hold_threshold_seconds=hold_threshold,
            double_tap_window_seconds=double_tap_window,
        )