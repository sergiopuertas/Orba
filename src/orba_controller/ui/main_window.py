from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QListWidget,
    QMainWindow,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MidiMonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ORBA MIDI Monitor")
        self.resize(900, 600)

        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.status_label = QLabel("Status: ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.status_label)

        self.port_list = QListWidget()
        self.port_list.addItems(["Mock Orba Input", "Mock Orba Output"])
        layout.addWidget(QLabel("Available MIDI ports"))
        layout.addWidget(self.port_list)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlainText(
            "ORBA Controller started.\n"
            "Waiting for MIDI input from the Orba device.\n"
            "This view is a safe placeholder while hardware validation is pending."
        )
        layout.addWidget(QLabel("Recent MIDI activity"))
        layout.addWidget(self.log_view)

        self.setCentralWidget(central)


def launch_monitor_window() -> None:
    app = QApplication.instance() or QApplication([])
    window = MidiMonitorWindow()
    window.show()
    app.exec()
