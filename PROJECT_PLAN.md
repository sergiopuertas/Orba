orba-monitor --capture --port "Artiphon Orba MIDI" --duration 18 --export tilt_levels.json# ORBA Controller — Project Plan

## 1. Scope

This repository begins with a safe, modular foundation for the Artiphon Orba 1. The initial goal is to create a reliable MIDI monitor, a compatible project structure, and an architecture that can later support gesture detection, assistant workflows, and hardware interaction without invalid assumptions.

## 2. Confirmed environment

- OS: macOS 15 (Darwin arm64)
- Python: 3.12.10
- Project target: Python >= 3.11
- Storage and runtime: local workspace with a venv managed in the repository

## 3. Architecture

The project follows a layered design:

1. Hardware layer: device discovery and transport management for USB-C and BLE MIDI
2. MIDI layer: raw transport decoding and normalized events
3. Gesture engine: tap, hold, move, shake, combo recognition
4. Command bus: actions mapped to device profiles
5. Integrations: Teams, Spotify, calendar, macOS automation
6. Assistant layer: push-to-talk, provider abstraction, notifications
7. UI layer: dashboard, diagnostics, calibration tools
8. Persistence layer: settings, profiles, and device state storage

## 4. Dependencies

Primary runtime dependencies:

- PySide6 for the GUI
- mido for MIDI parsing and transport helpers
- python-rtmidi for native MIDI access on macOS
- httpx for local HTTP APIs and future integrations
- pydantic for data validation
- PyYAML for profile configuration
- keyring for secure credential storage

Development dependencies:

- pytest
- ruff

## 5. Decisions and constraints

- The initial scope avoids risky SysEx or firmware modification.
- No undocumented Orba 2 register addresses are used for Orba 1.
- The system treats Orba-specific features as experimental until validated with hardware.
- The app starts in a safe, dry-run mode for any unapproved external automation.
- The gesture engine is designed to prioritize combo detection over individual pad actions.

## 6. Risks

- BLE MIDI access depends on the OS and driver stack available on the user machine.
- Orba 1 volume, vibration, and LED control need protocol validation before they are considered production features.
- Some integrations require user permissions and runtime credentials.
- AI assistant providers may require provider-specific adapters and local event hooks.

## 7. Confirmed capabilities

- Python 3.12 environment available on macOS.
- MIDI port enumeration and monitor foundation is implemented.
- Live MIDI input from the Artiphon Orba has been verified with real note and control-change messages.
- Calibration exports include elapsed receive time for each event.
- New calibration exports preserve program-change, pitchwheel, and pressure fields; `--inspect-capture` summarizes these signals without assigning semantics.
- A generic tap, hold, and double-tap engine is available through the event bus and a no-action live monitor.
- Live checks on channel 9, note 49 confirmed short taps, double taps, and a 1.42-second hold.
- Guided pad map records pads 1, 2, 5, and 8 across normal, Teams, and two additional program modes.
- The universal profile has mode-aware dry-run bindings for volume, undo, Spotify play/pause, Teams mute, and LLM open.
- The live gesture monitor retries the CoreMIDI input after port removal and re-enumeration.
- Project architecture is in place for modular extension.
- A safe simulation mode is available for UI and event testing.

## 8. Experimental capabilities

- Orba 1 hardware volume control
- Orba 1 vibration toggling
- LED RGB control
- direct battery state reporting
- advanced custom haptic patterns

These are explicitly documented as future phases pending verified protocol access.

## 9. Testing plan

- Unit tests for MIDI parsing and normalized event creation
- port discovery smoke tests using mocked device lists
- UI smoke tests for monitor startup
- future hardware-phase validation with live Orba sessions

## 10. Phase plan

### Phase 0 – environment and hardware recognition

- inspect workspace
- confirm OS and Python
- review Orba references and constraints
- define architecture and risks
- create this plan

### Phase 1 – MIDI monitor

- [x] detect available MIDI ports
- [x] connect to input with automatic reconnect in gesture monitor
- [x] visualize raw events
- [x] normalize note, control, program, pitchwheel, and pressure messages
- [x] export and inspect timestamped JSON logs

### Phase 2 – gesture engine

- [x] generic tap, hold, and double-tap recognition for note events
- [x] publish recognized gestures through the event bus
- [x] safe live monitor mode with no action execution
- [x] YAML profile thresholds and simulated action mapping (no external action execution)
- [x] replay timestamped calibration sessions with optional simulated action output
- [x] profile-defined ordered gesture sequences with channel/note filters and time windows
- [x] opt-in simultaneous note combos and thresholded CC movement events
- [x] guided capture of physical pad to MIDI note mappings by mode
- [x] mode-aware command bindings and pad-sequence definitions (dry-run only; no playlists)
- [x] extend pad map with pads 4 and 6
- [x] configure Spotify swipe sequences in normal mode as requested
- [ ] verify swipe timing and command behavior with live dry-run gestures
- [ ] label swipe direction and tilt semantics before enabling volume control

### Phase 3 – command bus and integrations

- [x] local in-memory event bus
- [x] command bus with dry-run enabled by default and explicit handler registration
- [x] route simulated profile actions from live monitoring and replay through the command bus
- [x] read-only Spotify currently-playing and Microsoft Graph presence clients with injected tokens
- [x] explicit Keychain token storage and provider callbacks
- [x] opt-in macOS volume/undo and Spotify transport handlers behind `--execute-actions`
- [ ] OAuth consent flow and automatic token refresh
- [ ] Teams mute handler after confirming the supported client and shortcut
- [ ] configure LLM URL and enable browser-open action
- [ ] additional Mac automation wrappers (permission-gated and opt-in)

### Phase 4 – hardware investigation

- validate Orba volume protocol
- validation of haptics and LEDs

### Phase 5 – assistant

- push-to-talk
- provider abstraction
- task and notification flow

### Phase 6 – LED feedback

- audio meter simulation
- physical LED channel integration only after validation

### Phase 7 – final app

- tray app, reconnect logic, settings, diagnostics, and docs
