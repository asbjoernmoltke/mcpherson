"""Control + status panels.

Each panel emits Qt signals for user actions (wired by the MainWindow to the
worker's queued slots) and has an ``update(snapshot)`` method to refresh its
read-outs from the periodic status snapshot. Panels never touch hardware
directly.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QProgressBar, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from ..widgets import LabeledValue, StatusLamp


def _lamp_state(ok: bool) -> str:
    return "ok" if ok else "bad"


class CameraPanel(QGroupBox):
    cooldown_requested = pyqtSignal(float)
    warmup_requested = pyqtSignal()
    exposure_changed = pyqtSignal(float)

    def __init__(self):
        super().__init__("Camera")
        layout = QVBoxLayout(self)

        self._temp = LabeledValue("Temperature")
        self._status = LabeledValue("Status")
        self._cooler = StatusLamp("Cooler")
        self._stable = StatusLamp("Temp stable")
        self._ready = StatusLamp("Ready to acquire")
        for w in (self._temp, self._status, self._cooler, self._stable,
                  self._ready):
            layout.addWidget(w)

        grid = QGridLayout()
        self._setpoint = QDoubleSpinBox()
        self._setpoint.setRange(-120.0, 30.0)
        self._setpoint.setValue(-60.0)
        self._setpoint.setSuffix(" °C")
        self._cool_btn = QPushButton("Cool down")
        self._warm_btn = QPushButton("Warm up / shutdown")
        grid.addWidget(self._setpoint, 0, 0)
        grid.addWidget(self._cool_btn, 0, 1)
        grid.addWidget(self._warm_btn, 1, 0, 1, 2)

        self._exposure = QDoubleSpinBox()
        self._exposure.setRange(0.0001, 600.0)
        self._exposure.setDecimals(4)
        self._exposure.setValue(0.1)
        self._exposure.setSuffix(" s exposure")
        grid.addWidget(self._exposure, 2, 0, 1, 2)
        layout.addLayout(grid)

        self._cool_btn.clicked.connect(
            lambda: self.cooldown_requested.emit(self._setpoint.value()))
        self._warm_btn.clicked.connect(self.warmup_requested.emit)
        self._exposure.valueChanged.connect(self.exposure_changed.emit)

    def update(self, s: dict) -> None:
        self._temp.set_value(f"{s['temperature']:.1f} °C")
        self._status.set_value(s["camera"])
        self._cooler.set_state(_lamp_state(s["cooler_on"]))
        self._stable.set_state(_lamp_state(s["stable"]))
        self._ready.set_state(_lamp_state(s["can_acquire"]))


class VacuumPanel(QGroupBox):
    def __init__(self):
        super().__init__("Vacuum")
        layout = QVBoxLayout(self)
        self._pressure = LabeledValue("Pressure")
        self._ok = StatusLamp("Safe to cool")
        layout.addWidget(self._pressure)
        layout.addWidget(self._ok)

    def update(self, s: dict) -> None:
        self._pressure.set_value(s["vacuum"])
        self._ok.set_state(_lamp_state(s["vacuum_ok"]))


class GratingPanel(QGroupBox):
    home_requested = pyqtSignal()
    goto_requested = pyqtSignal(float)
    stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__("Grating")
        layout = QVBoxLayout(self)
        self._position = LabeledValue("Position (steps)")
        self._status = LabeledValue("Status")
        layout.addWidget(self._position)
        layout.addWidget(self._status)

        grid = QGridLayout()
        self._wavelength = QDoubleSpinBox()
        self._wavelength.setRange(0.0, 2000.0)
        self._wavelength.setValue(500.0)
        self._wavelength.setSuffix(" nm")
        self._goto_btn = QPushButton("Go to λ")
        self._home_btn = QPushButton("Home")
        self._stop_btn = QPushButton("Stop")
        grid.addWidget(self._wavelength, 0, 0)
        grid.addWidget(self._goto_btn, 0, 1)
        grid.addWidget(self._home_btn, 1, 0)
        grid.addWidget(self._stop_btn, 1, 1)
        layout.addLayout(grid)

        self._home_btn.clicked.connect(self.home_requested.emit)
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        self._goto_btn.clicked.connect(
            lambda: self.goto_requested.emit(self._wavelength.value()))

    def update(self, s: dict) -> None:
        self._position.set_value(f"{s['position']:,d}")
        self._status.set_value(s["grating"])


class ShutterLaserPanel(QGroupBox):
    shutter_toggled = pyqtSignal(bool)
    laser_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__("Shutter / Laser")
        layout = QVBoxLayout(self)
        self._shutter_lamp = StatusLamp("Shutter")
        self._laser_lamp = StatusLamp("Laser")
        layout.addWidget(self._shutter_lamp)
        layout.addWidget(self._laser_lamp)

        row = QHBoxLayout()
        self._shutter_open = QPushButton("Open shutter")
        self._shutter_close = QPushButton("Close shutter")
        row.addWidget(self._shutter_open)
        row.addWidget(self._shutter_close)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self._laser_on = QPushButton("Enable laser")
        self._laser_off = QPushButton("Disable laser")
        row2.addWidget(self._laser_on)
        row2.addWidget(self._laser_off)
        layout.addLayout(row2)

        self._shutter_open.clicked.connect(lambda: self.shutter_toggled.emit(True))
        self._shutter_close.clicked.connect(lambda: self.shutter_toggled.emit(False))
        self._laser_on.clicked.connect(lambda: self.laser_toggled.emit(True))
        self._laser_off.clicked.connect(lambda: self.laser_toggled.emit(False))

    def update(self, s: dict) -> None:
        self._shutter_lamp.set_state("warn" if s["shutter_open"] else "ok")
        self._laser_lamp.set_state("warn" if s["laser_on"] else "ok")


class AcquisitionPanel(QGroupBox):
    single_requested = pyqtSignal()
    scan_requested = pyqtSignal(float, float)
    abort_requested = pyqtSignal()

    def __init__(self):
        super().__init__("Acquisition")
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        self._wl_min = QDoubleSpinBox()
        self._wl_min.setRange(0.0, 2000.0)
        self._wl_min.setValue(350.0)
        self._wl_min.setSuffix(" nm")
        self._wl_max = QDoubleSpinBox()
        self._wl_max.setRange(0.0, 2000.0)
        self._wl_max.setValue(600.0)
        self._wl_max.setSuffix(" nm")
        self._frames = QSpinBox()
        self._frames.setRange(1, 1000)
        self._frames.setValue(1)
        self._frames.setPrefix("frames: ")
        grid.addWidget(self._wl_min, 0, 0)
        grid.addWidget(self._wl_max, 0, 1)
        grid.addWidget(self._frames, 1, 0, 1, 2)
        layout.addLayout(grid)

        row = QHBoxLayout()
        self._single_btn = QPushButton("Single")
        self._scan_btn = QPushButton("Scan")
        self._abort_btn = QPushButton("Abort")
        row.addWidget(self._single_btn)
        row.addWidget(self._scan_btn)
        row.addWidget(self._abort_btn)
        layout.addLayout(row)

        self._progress = QProgressBar()
        layout.addWidget(self._progress)

        self._single_btn.clicked.connect(self.single_requested.emit)
        self._scan_btn.clicked.connect(
            lambda: self.scan_requested.emit(self._wl_min.value(),
                                             self._wl_max.value()))
        self._abort_btn.clicked.connect(self.abort_requested.emit)

    @property
    def n_frames(self) -> int:
        return self._frames.value()

    def set_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)

    def set_busy(self, busy: bool) -> None:
        self._single_btn.setEnabled(not busy)
        self._scan_btn.setEnabled(not busy)

    def update(self, s: dict) -> None:
        pass
