# ORBA Controller

ORBA Controller is a macOS-focused application framework for the Artiphon Orba 1. This repository starts with a robust foundation for hardware discovery, MIDI monitoring, and future gesture-driven automation.

## Current status

This initial implementation includes:

- project scaffolding for a modular architecture
- MIDI event normalization and parsing foundations
- a simple executable monitor for exploring MIDI ports and messages
- a development plan for the full Orba integration roadmap

## Getting started

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
orba-monitor
```

## First calibration workflow

1. Connect the Orba via USB-C or Bluetooth MIDI.
2. Start the app.
3. Choose the Orba MIDI input in the port list.
4. Tap, press, tilt, shake, and spin through the pads.
5. Observe the raw events and the normalized representation.
6. Record the port, note, control, and timing values for the individual modes.

## Gesture monitor

The initial gesture engine recognizes generic MIDI note taps, holds, and double taps. It does not execute profile actions or assign Orba-specific meaning to control changes.

```bash
orba-monitor --gesture-monitor --port "Artiphon Orba MIDI" --duration 10
```

Tap or hold the Orba while the monitor is listening. A single tap is reported after the double-tap window expires; a second tap in that window is reported as a double tap.

Add `--simulate-actions` to print the action selected by the YAML profile. This only reports the mapping; it does not execute desktop or external actions. Use `--profile PATH` to select another profile.

Profile actions pass through the local `CommandBus`, which defaults to dry-run and publishes a `command.dry_run` result. The application registers macOS volume +/-5, foreground undo, and Spotify play/pause/next/previous handlers only when live execution is explicitly enabled. Those actions can change volume, send a keyboard shortcut to the foreground app, and control Spotify. Teams mute remains unavailable until its client/shortcut is confirmed; `llm.open` requires an HTTPS URL.

To execute registered actions in a live Orba session, use `--execute-actions` instead of `--simulate-actions`:

```bash
orba-monitor --gesture-monitor --port "Artiphon Orba MIDI" --duration 60 --execute-actions --pad-map captures/orba_pad_map_full.json
```

This can change system volume, send Cmd+Z to the foreground app, and control Spotify. macOS may ask for Automation or Accessibility permission. Teams mute is not registered until its desktop/web client and shortcut are confirmed. `llm.open` is not registered until `--llm-url https://...` is provided. Replay always remains dry-run.

Read-only Python adapters are available for Spotify's currently playing item and Microsoft Graph's signed-in work account presence. They accept an access-token string or token-provider callback; `KeyringTokenStore` can store and retrieve provider tokens in macOS Keychain. No token is stored automatically. Spotify requires the `user-read-currently-playing` scope; Graph presence requires delegated `Presence.Read` for a work or school account. OAuth consent and automatic token refresh are not implemented yet.

The gesture monitor watches for the MIDI input to disappear and reappear, then reopens it automatically. The default reconnect poll interval is 0.5 seconds and can be changed with `--reconnect-interval`.

Replay a timestamped calibration log without connecting the Orba:

```bash
orba-monitor --replay orba_capture.json --simulate-actions
```

## Orba mapping capture

New calibration logs preserve program changes, pitchwheel, and pressure values needed to identify modes and tilt. Keep the existing capture and write a separate labeled session:

```bash
orba-monitor --capture --port "Artiphon Orba MIDI" --duration 90 --export orba_mapping_capture.json
```

During that window, change to one mode at a time and test only one action at a time: Drum pads 4, 5, and 6; Chord mode 3 with a double tap on pad 5; then tilt left and right several times. Inspect the result with:

```bash
orba-monitor --inspect-capture orba_mapping_capture.json
```

This reports MIDI identifiers and value ranges; it does not infer a gesture meaning or execute application commands.

## Pad mapping capture

Record MIDI notes for selected physical pads in each named mode without overwriting existing files or executing actions:

```bash
orba-monitor --learn-pad-map --port "Artiphon Orba MIDI" --map-modes normal=0,teams=1,chord=2,mode3=3 --map-pads 1,2,5,8 --map-export captures/orba_pad_map.json
```

For each mode, switch the Orba to that mode and press Enter; then tap each prompted physical pad once. The default covers the four program numbers; `chord` is the Orba Chord mode and `mode3` remains a placeholder you can rename. The result records each pad's MIDI channel and note. Profile command bindings are still dry-run until the captured note IDs are reviewed.

To capture only swipe pads 4 and 6 while preserving the existing 1/2/5/8 map, extend it into a new file:

```bash
orba-monitor --learn-pad-map --port "Artiphon Orba MIDI" --map-modes normal=0,teams=1,chord=2,mode3=3 --map-pads 4,6 --map-base captures/orba_pad_map.json --map-export captures/orba_pad_map_full.json
```

The universal profile maps pad 2 to volume down (double tap: down twice; hold: mute toggle), pad 7 to volume up in normal mode (double tap: up twice; hold: no action), pad 8 to Back (Cmd+[), pad 1 to Undo (Cmd+Z), a single tap on pad 5 in normal mode toggles Spotify only when it is already running. In Chord mode (program 2), entering the mode opens ChatGPT and holding pad 5 invokes its configured Voice shortcut. If you configure a ChatGPT Voice shortcut, pass it with `--chatgpt-voice-shortcut`; if omitted, holding pad 5 opens ChatGPT and starts a new chat with the app’s default `⌥+Space` Chat Bar shortcut. Pad 5 in Teams mode remains mapped to `teams.toggle_mute`. Normal-mode swipes 5→6 and 5→4 remain mapped to Spotify next/previous.

Pad 5 has no double-tap action. The double-tap window is 0.3 seconds so the 5→6 and 5→4 swipe sequences can be recognized. A live session remains dry-run unless `--execute-actions` is supplied. Example (replace the Voice shortcut with the one configured in ChatGPT):

```bash
orba-monitor --gesture-monitor --port "Artiphon Orba MIDI" --duration 3600 --execute-actions --chatgpt-voice-shortcut "option+shift+space" --pad-map captures/orba_pad_map_full.json
```

The gesture monitor still requires the correct learned MIDI channel/note map. For pad 2 in normal mode the current capture expects channel 9, note 38; use `--simulate-actions` first to confirm its event is labeled `pad: 2` before enabling actions.

Logs captured before elapsed timestamps were added must be recaptured before replay; the command rejects them instead of guessing gesture timing.

Ordered gesture sequences can be added under `profile.sequences` in a YAML profile. Each step may filter by MIDI channel and note; `max_gap_seconds` limits the time between completed gestures. Sequence actions are only printed with `--simulate-actions`.

```yaml
profile:
	sequences:
		- name: tap_then_hold
			steps:
				- gesture: tap
					channel: 9
					note: 49
				- gesture: hold
					channel: 9
					note: 43
			max_gap_seconds: 1.0
			action: safe_ack
```

		Combos and CC movement detection are also opt-in through `profile.combos` and `profile.movements`. Combos require their configured notes to be held within `max_gap_seconds`; movement rules compare successive values from one configured CC stream and emit only changes meeting `min_delta`, subject to `cooldown_seconds`. This is a configuration example, not a confirmed Orba mapping. No combo or movement is enabled in the universal profile because the current capture is not labeled semantically.

		```yaml
		profile:
			combos:
				- name: pad_chord
					notes: [38, 42]
					channel: 9
					max_gap_seconds: 0.15
					action: noop
			movements:
				- name: expression_change
					control: 2
					channel: 9
					min_delta: 12
					cooldown_seconds: 0.2
					action: noop
		```

## Important caveat

The repo intentionally avoids any risky hardware modification or undocumented SysEx access. It focuses on safe, observable MIDI monitoring and modular extension points.


## Bluetooth and background use

On macOS, Orba BLE MIDI is paired once in Audio MIDI Setup → Window → Show MIDI Studio → Configure Bluetooth. CoreMIDI then exposes an input such as `Artiphon Orba Bluetooth`; the controller prefers that port and retries automatically after disconnects. It does not use the Orba app.

`ORBA Controller.app` runs as a menu-bar app and is started at login. Its menu shows connection status and offers “Reconectar ahora” and “Salir”. Use the Orba power button to reconnect after a deep sleep; the app keeps polling and reopens the BLE MIDI input when macOS exposes it again.
