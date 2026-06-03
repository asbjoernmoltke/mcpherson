"""Emergency-stop button and the global safety status banner."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EStopButton(QPushButton):
    """A large, always-visible emergency-stop button.

    Wired directly to ``SafetyManager.estop`` (not via the worker thread), so
    it fires immediately even while a scan is blocking the worker.
    """

    def __init__(self):
        super().__init__("EMERGENCY STOP")
        self.setMinimumHeight(64)
        self.setStyleSheet(
            "QPushButton { background-color: #c0392b; color: white;"
            " font-size: 18px; font-weight: bold; border-radius: 6px; }"
            "QPushButton:pressed { background-color: #e74c3c; }")


class SafetyBanner(QWidget):
    """A status banner that turns red on E-stop or any safety alarm."""

    cleared = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        self._label = QLabel("System nominal")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self._set_ok()

    def _set_ok(self) -> None:
        self.setStyleSheet("background-color: #1e3d1e;")
        self._label.setStyleSheet("color: #9be39b; font-weight: bold;")

    def show_alarm(self, message: str) -> None:
        self.setStyleSheet("background-color: #4d1414;")
        self._label.setStyleSheet("color: #ffb0b0; font-weight: bold;")
        self._label.setText(message)

    def show_nominal(self) -> None:
        self._set_ok()
        self._label.setText("System nominal")
