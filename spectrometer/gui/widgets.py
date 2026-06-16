"""Small reusable Qt widgets (ports of the old customtkinter kit)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class StatusLamp(QWidget):
    """A small coloured indicator dot with a text label."""

    _COLORS = {
        "ok": QColor(40, 200, 80),
        "warn": QColor(230, 180, 40),
        "bad": QColor(220, 60, 60),
        "off": QColor(120, 120, 120),
    }

    def __init__(self, label: str, state: str = "off"):
        super().__init__()
        self._state = state
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self._dot = _Dot(self._COLORS[state])
        self._text = QLabel(label)
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        layout.addStretch(1)

    def set_state(self, state: str) -> None:
        self._state = state
        self._dot.set_color(self._COLORS.get(state, self._COLORS["off"]))


class _Dot(QWidget):
    def __init__(self, color: QColor):
        super().__init__()
        self._color = color
        self.setFixedSize(14, 14)

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 12, 12)


class ConnectionBar(QWidget):
    """Per-device connection row: a status dot + '<Device>: online/offline'
    + a Connect/Disconnect button. Carries its device key and emits it, so the
    MainWindow can route the request to the right driver. A 'simulated'
    (amber) state flags a Dummy stand-in so it is never mistaken for real
    hardware (e.g. the shutter, which has no concrete driver yet)."""

    connect_requested = pyqtSignal(str)
    disconnect_requested = pyqtSignal(str)

    _GREEN = QColor(40, 200, 80)
    _AMBER = QColor(230, 180, 40)
    _GREY = QColor(120, 120, 120)

    def __init__(self, device_key: str, title: str | None = None):
        super().__init__()
        self.device_key = device_key
        self._title = title or device_key.title()
        self._connected = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self._dot = _Dot(self._GREY)
        self._text = QLabel("%s: offline" % self._title)
        self._btn = QPushButton("Connect")
        self._btn.setMaximumWidth(110)
        layout.addWidget(self._dot)
        layout.addWidget(self._text)
        layout.addStretch(1)
        layout.addWidget(self._btn)
        self._btn.clicked.connect(self._on_click)

    def _on_click(self) -> None:
        if self._connected:
            self.disconnect_requested.emit(self.device_key)
        else:
            self.connect_requested.emit(self.device_key)

    def set_connected(self, connected: bool, simulated: bool = False) -> None:
        self._connected = connected
        if not connected:
            color, state = self._GREY, "offline"
        elif simulated:
            color, state = self._AMBER, "simulated (no hardware)"
        else:
            color, state = self._GREEN, "online"
        self._dot.set_color(color)
        self._text.setText("%s: %s" % (self._title, state))
        self._btn.setText("Disconnect" if connected else "Connect")


class LabeledValue(QWidget):
    """A 'Name: value' read-out row."""

    def __init__(self, name: str, value: str = "--"):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self._name = QLabel(f"{name}:")
        self._value = QLabel(value)
        self._value.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._name)
        layout.addStretch(1)
        layout.addWidget(self._value)

    def set_value(self, value: str, *, alert: bool = False) -> None:
        self._value.setText(value)
        self._value.setStyleSheet(
            "font-weight: bold; color: #d33;" if alert else "font-weight: bold;")
