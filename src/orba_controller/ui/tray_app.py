from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from orba_controller.core.events import Event
from orba_controller.gesture import (
    ControlMovementMatcher,
    GestureComboMatcher,
    GestureEngine,
    GestureProfile,
    GestureSequenceMatcher,
    PadModeMapper,
)
from orba_controller.main import (
    _create_command_bus,
    _default_pad_map_path,
    _default_profile_path,
)
from orba_controller.midi.monitor import MidiMonitor


class OrbaTrayController:
    """Live Orba MIDI controller that lives in the macOS menu bar."""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.monitor = MidiMonitor(dry_run=False)
        self.profile = GestureProfile.load(_default_profile_path())
        map_path = _default_pad_map_path()
        self.pad_mapper = PadModeMapper.load(map_path, initial_mode="normal") if map_path else None
        self.engine = GestureEngine(
            hold_threshold_seconds=self.profile.hold_threshold_seconds,
            double_tap_window_seconds=self.profile.double_tap_window_seconds,
        )
        self.sequence_matcher = GestureSequenceMatcher(self.profile.sequences)
        self.combo_matcher = GestureComboMatcher(self.profile.combos)
        self.movement_matcher = ControlMovementMatcher(self.profile.movements)
        self.command_bus = _create_command_bus(
            execute_actions=True,
            llm_url=None,
            chatgpt_voice_shortcut=None,
        )
        self.started_at = time.monotonic()
        self.selected_port = self.monitor.resolve_input_port() or "Artiphon Orba Bluetooth"
        self.next_reconnect_at = 0.0
        self.next_presence_check_at = 0.0
        self.status = "Buscando Orba BLE…"
        self._setup_logging()

        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        self.tray = QSystemTrayIcon(icon, app)
        self.tray.setToolTip("ORBA Controller — buscando Orba BLE")
        self.menu = QMenu()
        self.status_action = QAction(self.status, self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)
        self.menu.addSeparator()
        self.reconnect_action = QAction("Reconectar ahora", self.menu)
        self.reconnect_action.triggered.connect(self.reconnect_now)
        self.menu.addAction(self.reconnect_action)
        self.menu.addSeparator()
        quit_action = QAction("Salir de ORBA Controller", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.timer = QTimer(app)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.app.aboutToQuit.connect(self.shutdown)
        self.poll()

    @staticmethod
    def _setup_logging() -> None:
        log_path = Path.home() / "Library" / "Logs" / "ORBA Controller.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_path,
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
        )

    def _set_status(self, value: str) -> None:
        if value == self.status:
            return
        self.status = value
        self.status_action.setText(value)
        self.tray.setToolTip(f"ORBA Controller — {value}")
        logging.info(value)

    def reconnect_now(self) -> None:
        self.monitor.close()
        self._reset_gesture_state()
        self.next_reconnect_at = 0.0
        self.next_presence_check_at = 0.0
        self._set_status("Reconectando Orba BLE…")
        self.poll()

    def _reset_gesture_state(self) -> None:
        self.engine = GestureEngine(
            hold_threshold_seconds=self.profile.hold_threshold_seconds,
            double_tap_window_seconds=self.profile.double_tap_window_seconds,
        )
        self.sequence_matcher = GestureSequenceMatcher(self.profile.sequences)
        self.combo_matcher = GestureComboMatcher(self.profile.combos)
        self.movement_matcher = ControlMovementMatcher(self.profile.movements)

    def poll(self) -> None:
        try:
            now = time.monotonic()
            if self.monitor.connected and now >= self.next_presence_check_at:
                self.next_presence_check_at = now + 0.75
                resolved = self.monitor.resolve_input_port(self.selected_port)
                if resolved is None or resolved != self.selected_port:
                    self.monitor.close()
                    self._reset_gesture_state()
                    if resolved is not None:
                        self.selected_port = resolved
                    self.next_reconnect_at = now
                    self._set_status("Se perdió Orba BLE — reconectando…")

            if not self.monitor.connected and now >= self.next_reconnect_at:
                resolved = self.monitor.resolve_input_port(self.selected_port)
                if resolved is None:
                    self._set_status("Orba BLE desconectado — buscando…")
                else:
                    self.selected_port = resolved
                    if self.monitor.connect(self.selected_port):
                        self._reset_gesture_state()
                        self.started_at = time.monotonic()
                        self.next_presence_check_at = self.started_at + 0.75
                        transport = "BLE" if "bluetooth" in self.selected_port.casefold() else "MIDI"
                        self._set_status(f"Conectado: {self.selected_port} ({transport})")
                    else:
                        self._set_status("Reintentando Orba BLE…")
                        logging.warning("MIDI reconnect failed: %s", self.monitor.last_error)
                self.next_reconnect_at = time.monotonic() + 0.75

            if self.monitor.connected:
                for message in self.monitor.read_messages(limit=256):
                    message["elapsed_seconds"] = time.monotonic() - self.started_at
                    previous_mode = self.pad_mapper.current_mode if self.pad_mapper else None
                    if self.pad_mapper is not None:
                        message = self.pad_mapper.annotate(message)
                    if (
                        message.get("type") == "program_change"
                        and message.get("mode") != previous_mode
                    ):
                        self._emit(Event("mode.changed", {
                            "mode": message.get("mode"),
                            "program": message.get("program"),
                            "elapsed_seconds": message["elapsed_seconds"],
                        }))
                    for event in self.movement_matcher.process(message):
                        self._report_gesture(event)
                    for event in self.combo_matcher.process(message):
                        self._report_gesture(event)
                    for event in self.engine.process(message):
                        self._report_gesture(event)
                if self.monitor.last_error:
                    logging.warning("MIDI read failed: %s", self.monitor.last_error)
                    self.monitor.close()
                    self._reset_gesture_state()
                    self.next_reconnect_at = 0.0
                    self._set_status("Se perdió Orba BLE — reconectando…")

            elapsed = time.monotonic() - self.started_at
            for event in self.engine.flush_pending(elapsed):
                self._report_gesture(event)
            for event in self.sequence_matcher.flush_pending(elapsed):
                self._emit(event)
        except Exception:
            logging.exception("Unhandled error in Orba controller poll")
            self.monitor.close()
            self._reset_gesture_state()
            self.next_reconnect_at = time.monotonic() + 1.0
            self._set_status("Error MIDI — reintentando")

    def _report_gesture(self, event: Event) -> None:
        sequences = self.sequence_matcher.process(event)
        if not self.sequence_matcher.is_deferred(event):
            self._emit(event)
        for sequence in sequences:
            self._emit(sequence)

    def _emit(self, event: Event) -> None:
        action_event = self.profile.map_gesture(event)
        if action_event is None:
            return
        result = self.command_bus.dispatch(action_event)
        logging.info("%s -> %s", action_event.payload.get("action"), result.as_dict())
        if result.name in {"command.failed", "command.rejected"}:
            self.tray.showMessage(
                "ORBA Controller",
                f"No se pudo ejecutar {result.payload.get('action', 'la acción')}",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

    def shutdown(self) -> None:
        self.timer.stop()
        self.monitor.close()
        self.tray.hide()
        logging.info("ORBA Controller stopped")


def main() -> int:
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ORBA Controller")
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        logging.error("macOS menu bar is not available")
        return 1
    OrbaTrayController(app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
