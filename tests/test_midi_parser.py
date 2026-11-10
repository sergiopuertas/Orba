from orba_controller.midi.event_models import MidiEvent, parse_midi_message


def test_parse_note_on_message():
    event = parse_midi_message({"type": "note_on", "note": 60, "velocity": 90, "channel": 0})

    assert isinstance(event, MidiEvent)
    assert event.type == "note_on"
    assert event.note == 60
    assert event.velocity == 90
    assert event.channel == 0


def test_parse_cc_message_and_known_fields():
    event = parse_midi_message({"type": "control_change", "control": 74, "value": 63, "channel": 0})

    assert event.type == "control_change"
    assert event.control == 74
    assert event.value == 63
    assert event.channel == 0


def test_parse_program_change_pitchwheel_and_pressure_fields():
    program = parse_midi_message({"type": "program_change", "channel": 9, "program": 3})
    pitch = parse_midi_message({"type": "pitchwheel", "channel": 9, "pitch": -321})
    pressure = parse_midi_message({"type": "aftertouch", "channel": 9, "value": 47})

    assert program.as_dict()["program"] == 3
    assert program.channel == 9
    assert pitch.as_dict()["pitch"] == -321
    assert pitch.channel == 9
    assert pressure.as_dict()["pressure"] == 47
    assert pressure.value == 47
