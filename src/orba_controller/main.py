from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from orba_controller.core.command_bus import CommandBus
from orba_controller.core.events import Event
from orba_controller.gesture import (
    ControlMovementMatcher,
    GestureComboMatcher,
    GestureEngine,
    GestureProfile,
    GestureSequenceMatcher,
    PadModeMapper,
)
from orba_controller.integrations.macos_actions import MacOSActionHandlers
from orba_controller.midi.calibration import CalibrationSession
from orba_controller.midi.monitor import MidiMonitor


def _list_ports() -> None:
    monitor = MidiMonitor(dry_run=False)
    for port in monitor.list_ports():
        print(f"{port.name} | input={port.is_input} output={port.is_output} kind={port.kind}")


def _default_profile_path() -> Path:
    relative_path = Path("config") / "profiles" / "universal.yaml"
    candidates = (
        Path(__file__).resolve().parents[2] / relative_path,
        Path.cwd() / relative_path,
        Path(sys.prefix) / relative_path,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[-1])


def _default_pad_map_path() -> Path | None:
    relative_paths = (
        Path("captures") / "orba_pad_map_full.json",
        Path("captures") / "orba_pad_map.json",
    )
    roots = (
        Path(__file__).resolve().parents[2],
        Path.cwd(),
        Path(sys.prefix),
    )
    return next(
        (root / relative for root in roots for relative in relative_paths
         if (root / relative).is_file()),
        None,
    )


def _report_action(
    profile: GestureProfile,
    event: Event,
    command_bus: CommandBus,
) -> None:
    action_event = profile.map_gesture(event)
    if action_event is None:
        return
    label = "SIMULATED" if command_bus.dry_run else "ACTION"
    print(f"{label} {action_event.as_dict()}")
    command_result = command_bus.dispatch(action_event)
    print(f"COMMAND {command_result.as_dict()}")


def _create_command_bus(
    *, execute_actions: bool, llm_url: str | None,
    chatgpt_voice_shortcut: str | None = None,
) -> CommandBus:
    command_bus = CommandBus(dry_run=not execute_actions)
    if execute_actions:
        handlers = (
            MacOSActionHandlers(llm_url=llm_url)
            if chatgpt_voice_shortcut is None
            else MacOSActionHandlers(
                llm_url=llm_url,
                chatgpt_voice_shortcut=chatgpt_voice_shortcut,
            )
        )
        handlers.register(command_bus)
    return command_bus


def _probe_live(port_name: str | None, duration: float) -> int:
    import mido

    monitor = MidiMonitor(dry_run=False)
    selected_port = monitor.resolve_input_port(port_name)
    if selected_port is None:
        print(f"INPUT NOT FOUND: {selected_port}")
        return 1
    print(f"INPUT FOUND: {selected_port}")

    try:
        port = mido.open_input(selected_port)
    except Exception as exc:  # noqa: BLE001 - RtMidi backend exceptions vary by platform.
        print(f"INPUT OPEN FAILED: {exc}")
        return 1

    print(f"INPUT OPENED: {selected_port}")
    print(f"Play or tap the Orba now; listening for {max(duration, 0.1):g}s.")
    deadline = time.monotonic() + max(duration, 0.1)
    count = 0
    try:
        while time.monotonic() < deadline:
            for message in port.iter_pending():
                count += 1
                print(f"LIVE {message}")
            time.sleep(0.01)
    except Exception as exc:  # noqa: BLE001 - RtMidi read errors vary by platform.
        print(f"MIDI READ FAILED: {exc}")
        return 1
    finally:
        port.close()

    if count:
        print(f"LIVE TRAFFIC CONFIRMED: {count} MIDI messages received.")
        return 0

    print("NO LIVE TRAFFIC: the input is visible and open, but no MIDI messages arrived.")
    return 2


def _capture_calibration(port: str | None, dry_run: bool, duration: float, export_path: str | None) -> int:
    monitor = MidiMonitor(dry_run=dry_run)
    if not monitor.connect(port):
        print(f"Unable to open the selected MIDI port: {monitor.last_error or 'unknown MIDI open failure'}")
        return 1

    session = CalibrationSession(name="Orba 1 calibration")
    capture_started = time.monotonic()
    deadline = capture_started + max(duration, 0.1)

    try:
        while time.monotonic() < deadline:
            for message in monitor.read_messages(limit=25):
                session.record_event({
                    **message,
                    "elapsed_seconds": round(time.monotonic() - capture_started, 6),
                })
            time.sleep(0.05)
    finally:
        monitor.close()

    if export_path:
        output = os.path.abspath(export_path)
        session.export_json(output)
        print(f"Calibration log exported to {output}")
    else:
        print(json.dumps(session.as_dict(), indent=2))

    if not session.events:
        print("No MIDI messages received during capture.")
        return 2

    print(f"Captured {len(session.events)} MIDI messages.")
    return 0


def _monitor_gestures(
    port: str | None,
    duration: float,
    profile_path: str | None = None,
    simulate_actions: bool = False,
    reconnect_interval_seconds: float = 0.5,
    pad_map_path: str | None = None,
    execute_actions: bool = False,
    llm_url: str | None = None,
    chatgpt_voice_shortcut: str | None = None,
) -> int:
    try:
        profile = GestureProfile.load(profile_path or _default_profile_path())
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"Unable to load gesture profile: {exc}")
        return 1

    monitor = MidiMonitor(dry_run=False)
    selected_port = monitor.resolve_input_port(port) or port or "Artiphon Orba Bluetooth"
    selected_pad_map = Path(pad_map_path) if pad_map_path else _default_pad_map_path()
    pad_mapper = None
    if selected_pad_map is not None:
        try:
            pad_mapper = PadModeMapper.load(selected_pad_map, initial_mode="normal")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Unable to load pad map: {exc}")
            return 1
    elif profile.bindings or any(
        step.pad is not None for sequence in profile.sequences for step in sequence.steps
    ):
        print("Pad map not found; physical-pad bindings cannot be resolved.")

    engine = GestureEngine(
        hold_threshold_seconds=profile.hold_threshold_seconds,
        double_tap_window_seconds=profile.double_tap_window_seconds,
    )
    sequence_matcher = GestureSequenceMatcher(profile.sequences)
    combo_matcher = GestureComboMatcher(profile.combos)
    movement_matcher = ControlMovementMatcher(profile.movements)

    def reset_gesture_state() -> None:
        nonlocal engine, sequence_matcher, combo_matcher, movement_matcher
        engine = GestureEngine(
            hold_threshold_seconds=profile.hold_threshold_seconds,
            double_tap_window_seconds=profile.double_tap_window_seconds,
        )
        sequence_matcher = GestureSequenceMatcher(profile.sequences)
        combo_matcher = GestureComboMatcher(profile.combos)
        movement_matcher = ControlMovementMatcher(profile.movements)

    try:
        command_bus = _create_command_bus(
            execute_actions=execute_actions,
            llm_url=llm_url,
            chatgpt_voice_shortcut=chatgpt_voice_shortcut,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Unable to enable application actions: {exc}")
        return 1
    monitor_started = time.monotonic()
    deadline = monitor_started + max(duration, 0.1)
    gesture_count = 0
    action_mode = (
        "mapped actions will execute"
        if execute_actions
        else "mapped actions will be simulated"
        if simulate_actions
        else "no actions will be executed"
    )
    print(
        f"Listening for note gestures for {max(duration, 0.1):g}s on {selected_port}; "
        f"{action_mode}. Automatic reconnect is enabled."
    )

    def emit_gesture(event: Event) -> None:
        nonlocal gesture_count
        gesture_count += 1
        print(f"GESTURE {event.as_dict()}")
        if simulate_actions or execute_actions:
            _report_action(profile, event, command_bus)

    def report_gesture(event: Event) -> None:
        sequence_events = sequence_matcher.process(event)
        if not sequence_matcher.is_deferred(event):
            emit_gesture(event)
        for sequence_event in sequence_events:
            emit_gesture(sequence_event)

    try:
        while time.monotonic() < deadline:
            resolver = getattr(monitor, "resolve_input_port", None)
            resolved_port = resolver(selected_port) if callable(resolver) else (
                selected_port if monitor.is_input_available(selected_port) else None
            )
            port_available = resolved_port is not None
            if resolved_port is not None and resolved_port != selected_port:
                if monitor.connected:
                    monitor.close()
                    reset_gesture_state()
                selected_port = resolved_port
            if not port_available:
                if monitor.connected:
                    print(f"MIDI input disconnected: {selected_port}. Waiting to reconnect.")
                    monitor.close()
                    reset_gesture_state()
            elif not monitor.connected:
                if monitor.connect(selected_port):
                    reset_gesture_state()
                    print(f"MIDI input connected: {selected_port}")
                else:
                    print(
                        f"MIDI reconnect failed: {monitor.last_error or 'unknown error'}. "
                        f"Retrying in {reconnect_interval_seconds:g}s."
                    )

            if monitor.connected:
                for message in monitor.read_messages(limit=25):
                    message["elapsed_seconds"] = time.monotonic() - monitor_started
                    previous_mode = pad_mapper.current_mode if pad_mapper is not None else None
                    if pad_mapper is not None:
                        message = pad_mapper.annotate(message)
                    if (
                        message.get("type") == "program_change"
                        and message.get("mode") != previous_mode
                        and (simulate_actions or execute_actions)
                    ):
                        mode_event = Event(
                            "mode.changed",
                            {
                                "mode": message.get("mode"),
                                "program": message.get("program"),
                                "elapsed_seconds": message["elapsed_seconds"],
                            },
                        )
                        _report_action(profile, mode_event, command_bus)
                    for event in movement_matcher.process(message):
                        report_gesture(event)
                    for event in combo_matcher.process(message):
                        report_gesture(event)
                    for event in engine.process(message):
                        report_gesture(event)
                if monitor.last_error:
                    print(f"MIDI read failed: {monitor.last_error}. Reopening input.")
                    monitor.close()
                    reset_gesture_state()

            for event in engine.flush_pending(time.monotonic() - monitor_started):
                report_gesture(event)
            for event in sequence_matcher.flush_pending(time.monotonic() - monitor_started):
                emit_gesture(event)
            time.sleep(0.01 if monitor.connected else max(reconnect_interval_seconds, 0.05))
    finally:
        monitor.close()

    final_time = time.monotonic() - monitor_started + engine.double_tap_window_seconds + 0.001
    for event in engine.flush_pending(final_time):
        report_gesture(event)
    for event in sequence_matcher.flush_pending(
        final_time + max((rule.max_gap_seconds for rule in sequence_matcher.rules), default=0.0) + 0.001
    ):
        emit_gesture(event)

    if gesture_count:
        print(f"Gesture monitoring complete: {gesture_count} gesture events.")
        return 0

    print("No note gestures recognized during this session.")
    return 2


def _replay_calibration(
    capture_path: str,
    profile_path: str | None = None,
    simulate_actions: bool = False,
    pad_map_path: str | None = None,
) -> int:
    try:
        profile = GestureProfile.load(profile_path or _default_profile_path())
        capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"Unable to load replay input: {exc}")
        return 1

    if not isinstance(capture, dict) or not isinstance(capture.get("events"), list):
        print("Invalid calibration log: expected an events list.")
        return 1

    selected_pad_map = Path(pad_map_path) if pad_map_path else _default_pad_map_path()
    pad_mapper = None
    if selected_pad_map is not None:
        try:
            pad_mapper = PadModeMapper.load(selected_pad_map, initial_mode="normal")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Unable to load pad map: {exc}")
            return 1

    timed_events: list[tuple[dict[str, object], float]] = []
    previous_time = -math.inf
    for index, message in enumerate(capture["events"], start=1):
        if not isinstance(message, dict):
            print(f"Invalid calibration event {index}: expected an object.")
            return 1
        event_time = message.get("elapsed_seconds")
        if (
            isinstance(event_time, bool)
            or not isinstance(event_time, (int, float))
            or not math.isfinite(event_time)
            or event_time < previous_time
        ):
            print(
                f"Calibration event {index} has missing, invalid, or out-of-order "
                "elapsed_seconds; recapture with the current version."
            )
            return 1
        previous_time = float(event_time)
        timed_events.append((message, previous_time))

    engine = GestureEngine(
        hold_threshold_seconds=profile.hold_threshold_seconds,
        double_tap_window_seconds=profile.double_tap_window_seconds,
    )
    sequence_matcher = GestureSequenceMatcher(profile.sequences)
    combo_matcher = GestureComboMatcher(profile.combos)
    movement_matcher = ControlMovementMatcher(profile.movements)
    command_bus = CommandBus()
    gesture_count = 0

    def emit_gesture(event: Event) -> None:
        nonlocal gesture_count
        gesture_count += 1
        print(f"GESTURE {event.as_dict()}")
        if simulate_actions:
            _report_action(profile, event, command_bus)

    def report_gesture(event: Event) -> None:
        sequence_events = sequence_matcher.process(event)
        if not sequence_matcher.is_deferred(event):
            emit_gesture(event)
        for sequence_event in sequence_events:
            emit_gesture(sequence_event)

    print(f"Replaying {len(timed_events)} timestamped MIDI messages.")
    for message, event_time in timed_events:
        if pad_mapper is not None:
            message = pad_mapper.annotate(message)
        for event in movement_matcher.process({**message, "elapsed_seconds": event_time}):
            report_gesture(event)
        for event in combo_matcher.process({**message, "elapsed_seconds": event_time}):
            report_gesture(event)
        for event in engine.process(message, timestamp=event_time):
            report_gesture(event)

    if timed_events:
        final_time = timed_events[-1][1] + engine.double_tap_window_seconds + 0.001
        for event in engine.flush_pending(final_time):
            report_gesture(event)
        for event in sequence_matcher.flush_pending(
            final_time + max((rule.max_gap_seconds for rule in sequence_matcher.rules), default=0.0) + 0.001
        ):
            emit_gesture(event)

    if gesture_count:
        print(f"Replay complete: {gesture_count} gesture events.")
        return 0

    print("Replay complete: no note gestures recognized.")
    return 2


def _inspect_capture(capture_path: str) -> int:
    try:
        capture = json.loads(Path(capture_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Unable to load capture: {exc}")
        return 1

    if not isinstance(capture, dict) or not isinstance(capture.get("events"), list):
        print("Invalid calibration log: expected an events list.")
        return 1

    events = [event for event in capture["events"] if isinstance(event, dict)]
    event_types = Counter(event.get("type", "unknown") for event in events)
    print(f"Events: {len(events)}")
    print(f"Types: {dict(sorted(event_types.items()))}")

    notes: dict[int, Counter[int]] = defaultdict(Counter)
    programs: Counter[tuple[int | None, int | None]] = Counter()
    controls: dict[tuple[int | None, int], list[int]] = defaultdict(list)
    pitches: dict[int | None, list[int]] = defaultdict(list)
    pressures: dict[int | None, list[int]] = defaultdict(list)

    for event in events:
        channel = event.get("channel")
        event_type = event.get("type")
        if event_type in {"note_on", "note_off"} and isinstance(event.get("note"), int):
            notes[channel][event["note"]] += 1
        elif event_type == "program_change":
            program = event.get("program")
            programs[(channel, program if isinstance(program, int) else None)] += 1
        elif event_type == "control_change":
            control, value = event.get("control"), event.get("value")
            if isinstance(control, int) and isinstance(value, int):
                controls[(channel, control)].append(value)
        elif event_type in {"pitchwheel", "pitch_bend"}:
            pitch = event.get("pitch", event.get("value"))
            if isinstance(pitch, int):
                pitches[channel].append(pitch)
        elif event_type in {"aftertouch", "channel_pressure"}:
            pressure = event.get("pressure", event.get("value"))
            if isinstance(pressure, int):
                pressures[channel].append(pressure)

    print("Notes by channel:")
    for channel, values in sorted(notes.items()):
        print(f"  channel {channel}: {dict(sorted(values.items()))}")

    print("Mode/program changes:")
    if programs and all(program is not None for _, program in programs):
        for (channel, program), count in sorted(programs.items()):
            print(f"  channel {channel}: program {program} ({count})")
    elif programs:
        missing = sum(count for (_, program), count in programs.items() if program is None)
        print(f"  {missing} program changes lack their program number; recapture with this version")
    else:
        print("  none recorded")

    print("Control-change ranges:")
    for (channel, control), values in sorted(controls.items()):
        print(
            f"  channel {channel}, CC{control}: min={min(values)} max={max(values)} "
            f"samples={len(values)}"
        )

    for label, grouped_values in (("Pitchwheel", pitches), ("Pressure", pressures)):
        print(f"{label} ranges:")
        if not grouped_values:
            print("  none recorded")
        for channel, values in sorted(grouped_values.items()):
            print(f"  channel {channel}: min={min(values)} max={max(values)} samples={len(values)}")

    return 0


def _parse_mode_programs(value: str) -> dict[str, int]:
    modes: dict[str, int] = {}
    for item in value.split(","):
        name, separator, program_text = item.partition("=")
        if not separator or not name.strip():
            raise ValueError(f"Invalid mode assignment: {item}")
        program = int(program_text)
        if not 0 <= program <= 127:
            raise ValueError(f"MIDI program must be between 0 and 127: {program}")
        if name.strip() in modes:
            raise ValueError(f"Duplicate mode name: {name.strip()}")
        modes[name.strip()] = program
    if not modes:
        raise ValueError("At least one mode assignment is required")
    return modes


def _parse_pad_numbers(value: str) -> list[int]:
    pads = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not pads or any(not 1 <= pad <= 8 for pad in pads):
        raise ValueError("Pad numbers must be between 1 and 8")
    if len(set(pads)) != len(pads):
        raise ValueError("Pad numbers must be unique")
    return pads


def _learn_pad_map(
    port_name: str | None,
    mode_programs: dict[str, int],
    pad_numbers: list[int],
    export_path: str,
    *,
    input_fn=None,
    timeout_seconds: float = 10.0,
    base_path: str | None = None,
) -> int:
    output = Path(export_path).expanduser().resolve()
    if output.exists():
        print(f"Refusing to overwrite existing pad map: {output}")
        return 1
    if timeout_seconds <= 0:
        print("Pad timeout must be positive.")
        return 1

    pad_map: dict[str, dict[str, dict[str, int]]] = {}
    if base_path:
        try:
            base_data = json.loads(Path(base_path).read_text(encoding="utf-8"))
            if base_data.get("mode_programs") != mode_programs:
                print("Base pad map modes do not match the selected mode programs.")
                return 1
            base_pads = base_data.get("pads")
            if not isinstance(base_pads, dict):
                print("Base pad map has no valid pads object.")
                return 1
            pad_map = {
                mode: {str(pad): dict(mapping) for pad, mapping in pads.items()}
                for mode, pads in base_pads.items()
                if isinstance(pads, dict)
            }
        except (OSError, ValueError, AttributeError) as exc:
            print(f"Unable to load base pad map: {exc}")
            return 1

    prompt = input if input_fn is None else input_fn
    monitor = MidiMonitor(dry_run=False)
    if not monitor.connect(port_name):
        print(f"Unable to open the selected MIDI port: {monitor.last_error or 'unknown MIDI open failure'}")
        return 1

    try:
        for mode_name, program in mode_programs.items():
            print(f"\nSelect Orba mode '{mode_name}' (MIDI program {program}).")
            prompt("Press Enter when the Orba is in this mode.")
            pad_map.setdefault(mode_name, {})
            for pad in pad_numbers:
                if str(pad) in pad_map[mode_name]:
                    print(f"  pad {pad} already mapped; keeping the base mapping")
                    continue
                print(f"Tap physical pad {pad} once now (timeout {timeout_seconds:g}s).")
                deadline = time.monotonic() + timeout_seconds
                note_message = None
                while time.monotonic() < deadline:
                    for message in monitor.read_messages(limit=64):
                        if (
                            message.get("type") == "note_on"
                            and int(message.get("velocity") or 0) > 0
                        ):
                            note_message = message
                            break
                    if note_message is not None:
                        break
                    time.sleep(0.01)

                if note_message is None:
                    print(f"No note received for pad {pad} in mode '{mode_name}'. Map cancelled.")
                    return 1

                channel = int(note_message.get("channel", 0))
                note = int(note_message.get("note", 0))
                if any(
                    mapping["channel"] == channel and mapping["note"] == note
                    for mapping in pad_map[mode_name].values()
                ):
                    print(f"Duplicate MIDI note {note} received in mode '{mode_name}'. Map cancelled.")
                    return 1
                pad_map[mode_name][str(pad)] = {"channel": channel, "note": note}
                print(f"  pad {pad} -> channel {channel}, note {note}")

        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "mode_programs": mode_programs,
            "pads": pad_map,
        }
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except (EOFError, KeyboardInterrupt):
        print("Pad mapping cancelled; no file was written.")
        return 130
    finally:
        monitor.close()

    print(f"Pad map exported to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ORBA Controller launch entrypoint")
    parser.add_argument("--list-ports", action="store_true", help="Print available MIDI ports")
    parser.add_argument("--dry-run", action="store_true", help="Use simulated inputs instead of raw hardware")
    parser.add_argument("--port", type=str, default=None, help="Optional MIDI port name to open")
    parser.add_argument("--gui", action="store_true", help="Start the GUI monitor")
    parser.add_argument("--capture", action="store_true", help="Capture MIDI for calibration logging")
    parser.add_argument("--duration", type=float, default=5.0, help="Capture duration in seconds")
    parser.add_argument("--export", type=str, default=None, help="Write calibration capture to JSON")
    parser.add_argument("--diagnose", action="store_true", help="Diagnose whether each MIDI port can actually be opened")
    parser.add_argument("--probe-live", action="store_true", help="Open the real MIDI input and print any live messages for a short interval")
    parser.add_argument("--probe-seconds", type=float, default=5.0, help="Seconds to wait for live MIDI traffic in probe mode")
    parser.add_argument("--gesture-monitor", action="store_true", help="Recognize note gestures without executing actions")
    parser.add_argument("--profile", type=str, default=None, help="YAML gesture profile path")
    parser.add_argument("--pad-map", type=str, default=None, help="Learned physical-pad to MIDI map JSON path")
    action_mode = parser.add_mutually_exclusive_group()
    action_mode.add_argument("--simulate-actions", action="store_true", help="Print profile-mapped actions without executing them")
    action_mode.add_argument("--execute-actions", action="store_true", help="Execute registered macOS/Spotify actions during live monitoring")
    parser.add_argument("--llm-url", type=str, default=None, help="HTTPS URL opened by llm.open when action execution is enabled")
    parser.add_argument("--chatgpt-voice-shortcut", type=str, default=None, help="ChatGPT Voice shortcut, for example option+shift+space")
    parser.add_argument("--reconnect-interval", type=float, default=0.5, help="Seconds between MIDI reconnect attempts")
    parser.add_argument("--replay", type=str, default=None, help="Replay a timestamped calibration JSON file")
    parser.add_argument("--inspect-capture", type=str, default=None, help="Summarize notes, mode changes, and movement signals in a capture")
    parser.add_argument("--learn-pad-map", action="store_true", help="Interactively record physical pad numbers to MIDI notes")
    parser.add_argument(
        "--map-modes",
        type=str,
        default="normal=0,teams=1,chord=2,mode3=3",
        help="Comma-separated mode=program assignments for pad-map capture",
    )
    parser.add_argument("--map-pads", type=str, default="1,2,5,8", help="Comma-separated physical pads to capture")
    parser.add_argument("--map-export", type=str, default="captures/orba_pad_map.json", help="New JSON path for the guided pad mapping")
    parser.add_argument("--map-base", type=str, default=None, help="Existing pad map to extend without overwriting it")
    parser.add_argument("--pad-timeout", type=float, default=10.0, help="Seconds to wait for each pad tap")
    args = parser.parse_args()

    if args.execute_actions and (not args.gesture_monitor or args.replay):
        parser.error("--execute-actions requires live --gesture-monitor and cannot be used with --replay")

    if args.learn_pad_map:
        try:
            mode_programs = _parse_mode_programs(args.map_modes)
            pad_numbers = _parse_pad_numbers(args.map_pads)
        except ValueError as exc:
            print(f"Invalid pad-map setup: {exc}")
            return 1
        return _learn_pad_map(
            args.port,
            mode_programs,
            pad_numbers,
            args.map_export,
            timeout_seconds=args.pad_timeout,
            base_path=args.map_base,
        )

    if args.list_ports:
        _list_ports()
        return 0

    if args.diagnose:
        monitor = MidiMonitor(dry_run=False)
        for item in monitor.diagnose_ports():
            print(f"{item['name']} | {item['type']} | openable={item['openable']}" + (f" | error={item['error']}" if 'error' in item else ''))
        return 0

    if args.probe_live:
        return _probe_live(args.port, args.probe_seconds)

    if args.replay:
        return _replay_calibration(args.replay, args.profile, args.simulate_actions, args.pad_map)

    if args.inspect_capture:
        return _inspect_capture(args.inspect_capture)

    if args.gesture_monitor:
        return _monitor_gestures(
            args.port,
            args.duration,
            args.profile,
            args.simulate_actions,
            args.reconnect_interval,
            args.pad_map,
            args.execute_actions,
            args.llm_url,
            args.chatgpt_voice_shortcut,
        )

    if args.gui:
        from orba_controller.ui.main_window import launch_monitor_window

        launch_monitor_window()
        return 0

    if args.capture:
        return _capture_calibration(args.port, args.dry_run, args.duration, args.export)

    monitor = MidiMonitor(dry_run=args.dry_run)
    if not monitor.connect(args.port):
        print(f"Unable to open the selected port. Falling back to dry-run mode. Error: {monitor.last_error or 'unknown MIDI open failure'}")
        monitor = MidiMonitor(dry_run=True)
        monitor.connect(None)

    print("Connected monitor mode:", "dry_run" if monitor.dry_run else "live")
    for message in monitor.read_messages(limit=10):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
