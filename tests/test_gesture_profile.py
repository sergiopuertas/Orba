import json

import pytest

from orba_controller import main
from orba_controller.core.events import Event
from orba_controller.gesture import GestureProfile


def test_profile_loads_thresholds_and_maps_actions(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Test\n"
        "  description: Test profile\n"
        "  gestures:\n"
        "    - name: tap\n"
        "      action: noop\n"
        "gesture_engine:\n"
        "  hold_threshold_seconds: 0.7\n"
        "  double_tap_window_seconds: 0.25\n",
        encoding="utf-8",
    )

    profile = GestureProfile.load(profile_path)
    action_event = profile.map_gesture(Event("gesture.tap", {"note": 49}))

    assert profile.name == "Test"
    assert profile.hold_threshold_seconds == 0.7
    assert profile.double_tap_window_seconds == 0.25
    assert action_event is not None
    assert action_event.name == "action.simulated"
    assert action_event.payload["action"] == "noop"
    assert profile.map_gesture(Event("gesture.double_tap")) is None


def test_universal_profile_maps_requested_pads_by_mode():
    profile_path = main._default_profile_path()
    profile = GestureProfile.load(profile_path)

    def mapped(pad, mode):
        event = Event("gesture.tap", {"pad": pad, "mode": mode})
        action = profile.map_gesture(event)
        return action.payload["action"] if action is not None else None

    assert mapped(2, "normal") == "volume.down"
    assert mapped(8, "teams") == "volume.up"
    assert mapped(1, "mode2") == "system.undo"
    assert mapped(5, "normal") == "spotify.play_pause"
    assert mapped(5, "teams") == "teams.toggle_mute"

    llm_event = Event("gesture.hold", {"pad": 5, "mode": "normal"})
    assert profile.map_gesture(llm_event).payload["action"] == "llm.open"
    assert {rule.name: rule.action for rule in profile.sequences} == {
        "spotify_next": "spotify.next",
        "spotify_previous": "spotify.previous",
    }
    assert all(step.mode == "normal" for rule in profile.sequences for step in rule.steps)


def test_profile_rejects_duplicate_gesture_rules(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Invalid\n"
        "  gestures:\n"
        "    - name: tap\n"
        "      action: noop\n"
        "    - name: tap\n"
        "      action: safe_ack\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate gesture rule"):
        GestureProfile.load(profile_path)


def test_profile_loads_sequence_rules_and_maps_sequence_action(tmp_path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Sequence test\n"
        "  sequences:\n"
        "    - name: tap_then_hold\n"
        "      steps:\n"
        "        - gesture: tap\n"
        "          channel: 9\n"
        "          note: 49\n"
        "        - gesture: hold\n"
        "          channel: 9\n"
        "          note: 43\n"
        "      max_gap_seconds: 1.25\n"
        "      action: safe_ack\n",
        encoding="utf-8",
    )

    profile = GestureProfile.load(profile_path)
    action_event = profile.map_gesture(Event(
        "gesture.sequence",
        {"sequence": "tap_then_hold", "elapsed_seconds": 1.0},
    ))

    assert len(profile.sequences) == 1
    assert profile.sequences[0].max_gap_seconds == 1.25
    assert action_event is not None
    assert action_event.payload["action"] == "safe_ack"


def test_profile_loads_opt_in_combo_and_movement_rules(tmp_path):
    profile_path = tmp_path / "patterns.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Pattern test\n"
        "  combos:\n"
        "    - name: pad_chord\n"
        "      notes: [38, 42]\n"
        "      channel: 9\n"
        "      max_gap_seconds: 0.15\n"
        "      action: safe_ack\n"
        "  movements:\n"
        "    - name: expression_change\n"
        "      control: 2\n"
        "      channel: 9\n"
        "      min_delta: 12\n"
        "      cooldown_seconds: 0.2\n"
        "      action: noop\n",
        encoding="utf-8",
    )

    profile = GestureProfile.load(profile_path)
    combo_action = profile.map_gesture(Event(
        "gesture.combo", {"combo": "pad_chord", "notes": [38, 42]}
    ))
    movement_action = profile.map_gesture(Event(
        "gesture.move", {"movement": "expression_change", "control": 2}
    ))

    assert profile.combos[0].notes == (38, 42)
    assert profile.movements[0].min_delta == 12
    assert combo_action is not None and combo_action.payload["action"] == "safe_ack"
    assert movement_action is not None and movement_action.payload["action"] == "noop"


def test_gesture_monitor_reports_invalid_profile_without_opening_port(tmp_path, capsys):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("invalid: true\n", encoding="utf-8")

    result = main._monitor_gestures("Artiphon Orba MIDI", 1, str(profile_path))

    assert result == 1
    assert "Unable to load gesture profile" in capsys.readouterr().out


def test_default_profile_resolves_from_installed_prefix_outside_repository(
    monkeypatch, tmp_path
):
    installed_prefix = tmp_path / "venv"
    installed_profile = installed_prefix / "config" / "profiles" / "universal.yaml"
    installed_profile.parent.mkdir(parents=True)
    installed_profile.write_text("profile: {}\n", encoding="utf-8")
    fake_module = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "orba_controller" / "main.py"
    monkeypatch.setattr(main, "__file__", str(fake_module))
    monkeypatch.setattr(main.sys, "prefix", str(installed_prefix))
    monkeypatch.chdir(tmp_path)

    assert main._default_profile_path() == installed_profile


def test_replay_uses_capture_timestamps_and_simulates_mapped_action(tmp_path, capsys):
    capture_path = tmp_path / "capture.json"
    capture_path.write_text(
        json.dumps({
            "events": [
                {"type": "note_on", "channel": 9, "note": 49, "velocity": 80, "elapsed_seconds": 0.0},
                {"type": "note_off", "channel": 9, "note": 49, "velocity": 20, "elapsed_seconds": 0.05},
                {"type": "note_on", "channel": 9, "note": 49, "velocity": 80, "elapsed_seconds": 0.2},
                {"type": "note_off", "channel": 9, "note": 49, "velocity": 20, "elapsed_seconds": 0.25},
            ]
        }),
        encoding="utf-8",
    )

    result = main._replay_calibration(str(capture_path), simulate_actions=True)

    output = capsys.readouterr().out
    assert result == 0
    assert output.count("GESTURE {'name': 'gesture.double_tap'") == 1
    assert "SIMULATED {'name': 'action.simulated'" in output
    assert "COMMAND {'name': 'command.dry_run'" in output


def test_replay_rejects_legacy_capture_without_timestamps(tmp_path, capsys):
    capture_path = tmp_path / "legacy.json"
    capture_path.write_text(
        json.dumps({
            "events": [{"type": "note_on", "channel": 9, "note": 49, "velocity": 80}]
        }),
        encoding="utf-8",
    )

    result = main._replay_calibration(str(capture_path))

    assert result == 1
    assert "recapture with the current version" in capsys.readouterr().out


def test_replay_emits_profile_defined_sequence(tmp_path, capsys):
    profile_path = tmp_path / "sequence-profile.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Sequence test\n"
        "  sequences:\n"
        "    - name: tap_then_hold\n"
        "      steps:\n"
        "        - gesture: tap\n"
        "          channel: 9\n"
        "          note: 49\n"
        "        - gesture: hold\n"
        "          channel: 9\n"
        "          note: 43\n"
        "      max_gap_seconds: 1.0\n"
        "      action: safe_ack\n",
        encoding="utf-8",
    )
    capture_path = tmp_path / "sequence-capture.json"
    capture_path.write_text(json.dumps({
        "events": [
            {"type": "note_on", "channel": 9, "note": 49, "velocity": 80, "elapsed_seconds": 0.0},
            {"type": "note_off", "channel": 9, "note": 49, "velocity": 20, "elapsed_seconds": 0.05},
            {"type": "note_on", "channel": 9, "note": 43, "velocity": 80, "elapsed_seconds": 0.2},
            {"type": "note_off", "channel": 9, "note": 43, "velocity": 20, "elapsed_seconds": 0.8},
        ]
    }), encoding="utf-8")

    result = main._replay_calibration(
        str(capture_path), profile_path=str(profile_path), simulate_actions=True
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "GESTURE {'name': 'gesture.sequence'" in output
    assert "tap_then_hold" in output
    assert "'action': 'safe_ack'" in output


def test_normal_mode_pad_swipe_triggers_next_without_play_pause(tmp_path, capsys):
    profile_path = tmp_path / "swipe-profile.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Swipe test\n"
        "  bindings:\n"
        "    - gesture: tap\n"
        "      pad: 5\n"
        "      mode: normal\n"
        "      action: spotify.play_pause\n"
        "  sequences:\n"
        "    - name: spotify_next\n"
        "      steps:\n"
        "        - gesture: tap\n"
        "          pad: 5\n"
        "          mode: normal\n"
        "        - gesture: tap\n"
        "          pad: 6\n"
        "          mode: normal\n"
        "      max_gap_seconds: 0.5\n"
        "      action: spotify.next\n",
        encoding="utf-8",
    )
    pad_map_path = tmp_path / "pad-map.json"
    pad_map_path.write_text(json.dumps({
        "mode_programs": {"normal": 0},
        "pads": {"normal": {
            "5": {"channel": 9, "note": 43},
            "6": {"channel": 9, "note": 45},
        }},
    }), encoding="utf-8")
    capture_path = tmp_path / "swipe.json"
    capture_path.write_text(json.dumps({
        "events": [
            {"type": "program_change", "channel": 0, "program": 0, "elapsed_seconds": 0.0},
            {"type": "note_on", "channel": 9, "note": 43, "velocity": 80, "elapsed_seconds": 0.0},
            {"type": "note_off", "channel": 9, "note": 43, "velocity": 20, "elapsed_seconds": 0.05},
            {"type": "note_on", "channel": 9, "note": 45, "velocity": 80, "elapsed_seconds": 0.2},
            {"type": "note_off", "channel": 9, "note": 45, "velocity": 20, "elapsed_seconds": 0.25},
        ]
    }), encoding="utf-8")

    result = main._replay_calibration(
        str(capture_path),
        profile_path=str(profile_path),
        simulate_actions=True,
        pad_map_path=str(pad_map_path),
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "'action': 'spotify.next'" in output
    assert "'action': 'spotify.play_pause'" not in output


def test_replay_emits_configured_combo_and_control_movement(tmp_path, capsys):
    profile_path = tmp_path / "patterns.yaml"
    profile_path.write_text(
        "profile:\n"
        "  name: Pattern replay\n"
        "  combos:\n"
        "    - name: pad_chord\n"
        "      notes: [38, 42]\n"
        "      channel: 9\n"
        "      max_gap_seconds: 0.15\n"
        "      action: safe_ack\n"
        "  movements:\n"
        "    - name: expression_change\n"
        "      control: 2\n"
        "      channel: 9\n"
        "      min_delta: 12\n"
        "      cooldown_seconds: 0.2\n"
        "      action: noop\n",
        encoding="utf-8",
    )
    capture_path = tmp_path / "patterns.json"
    capture_path.write_text(json.dumps({
        "events": [
            {"type": "control_change", "channel": 9, "control": 2, "value": 10, "elapsed_seconds": 0.0},
            {"type": "control_change", "channel": 9, "control": 2, "value": 25, "elapsed_seconds": 0.05},
            {"type": "note_on", "channel": 9, "note": 38, "velocity": 80, "elapsed_seconds": 0.1},
            {"type": "note_on", "channel": 9, "note": 42, "velocity": 80, "elapsed_seconds": 0.18},
        ]
    }), encoding="utf-8")

    result = main._replay_calibration(
        str(capture_path), profile_path=str(profile_path), simulate_actions=True
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "GESTURE {'name': 'gesture.move'" in output
    assert "GESTURE {'name': 'gesture.combo'" in output
    assert "'action': 'safe_ack'" in output
    assert "'action': 'noop'" in output