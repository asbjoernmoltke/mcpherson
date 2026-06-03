"""Small reusable Qt widgets (ports of the old customtkinter kit)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget


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

    def set_value(self, value: str) -> None:
        self._value.setText(value)
