"""Control + status panels.

Each panel emits Qt signals for user actions (wired by the MainWindow to the
worker's queued slots) and has an ``update(snapshot)`` method to refresh its
read-outs from the periodic status snapshot. Panels never touch hardware
directly.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QSpinBox, QVBoxLayout, QWidget)

from ..widgets import ConnectionBar, LabeledValue, StatusLamp


def _lamp_state(ok: bool) -> str:
    return "ok" if ok else "bad"


class CameraPanel(QGroupBox):
    cooldown_requested = pyqtSignal(float)
    warmup_requested = pyqtSignal()
    exposure_changed = pyqtSignal(float)
    trigger_changed = pyqtSignal(str)
    internal_shutter_changed = pyqtSignal(str)
    readout_changed = pyqtSignal(int)
    preamp_changed = pyqtSignal(int)
    em_gain_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__("Camera")
        layout = QVBoxLayout(self)

        self.conn = ConnectionBar("camera", "Camera")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)

        self._temp = LabeledValue("Temperature")
        self._status = LabeledValue("Status")
        self._cooler = StatusLamp("Cooler")
        self._stable = StatusLamp("Temp stable")
        self._cooled = StatusLamp("Cooled (low noise)")
        for w in (self._temp, self._status, self._cooler, self._stable,
                  self._cooled):
            layout.addWidget(w)

        # Cooldown / warm-up progress (driven by the status poll).
        self._cool_progress = QProgressBar()
        self._cool_progress.setRange(0, 100)
        self._cool_progress.setFormat("idle")
        layout.addWidget(self._cool_progress)

        grid = QGridLayout()
        self._setpoint = QDoubleSpinBox()
        self._setpoint.setRange(-100.0, -20.0)  # Newton DO920P rated range
        self._setpoint.setValue(-80.0)          # typical operating point
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

        # --- acquisition configuration (populated from camera caps) ----
        cfg = QGridLayout()
        cfg.addWidget(QLabel("Trigger"), 0, 0)
        self._trigger = QComboBox()
        cfg.addWidget(self._trigger, 0, 1)
        cfg.addWidget(QLabel("Int. shutter"), 1, 0)
        self._shutter = QComboBox()
        cfg.addWidget(self._shutter, 1, 1)
        cfg.addWidget(QLabel("A-D rate"), 2, 0)
        self._readout = QComboBox()
        cfg.addWidget(self._readout, 2, 1)
        cfg.addWidget(QLabel("Pre-amp gain"), 3, 0)
        self._preamp = QComboBox()
        cfg.addWidget(self._preamp, 3, 1)
        cfg.addWidget(QLabel("EM gain"), 4, 0)
        self._em_gain = QSpinBox()
        self._em_btn = QPushButton("Set")
        cfg.addWidget(self._em_gain, 4, 1)
        cfg.addWidget(self._em_btn, 4, 2)
        layout.addLayout(cfg)

        self._cool_btn.clicked.connect(
            lambda: self.cooldown_requested.emit(self._setpoint.value()))
        self._warm_btn.clicked.connect(self.warmup_requested.emit)
        self._exposure.valueChanged.connect(self.exposure_changed.emit)
        self._trigger.currentTextChanged.connect(self.trigger_changed.emit)
        self._shutter.currentTextChanged.connect(self.internal_shutter_changed.emit)
        self._readout.currentIndexChanged.connect(self.readout_changed.emit)
        self._preamp.currentIndexChanged.connect(self.preamp_changed.emit)
        self._em_btn.clicked.connect(
            lambda: self.em_gain_changed.emit(self._em_gain.value()))

    def set_capabilities(self, caps: dict) -> None:
        """Populate the config dropdowns from the (open) camera's reported
        options. Called once at start-up; signals are blocked during the
        programmatic fill so no spurious change is emitted."""
        def fill_combo(combo, items, current_index=None, current_text=None):
            combo.blockSignals(True)
            combo.clear()
            for it in items:
                combo.addItem(it)
            if current_index is not None and 0 <= current_index < len(items):
                combo.setCurrentIndex(current_index)
            elif current_text is not None:
                combo.setCurrentText(current_text)
            combo.setEnabled(bool(items))
            combo.blockSignals(False)

        fill_combo(self._trigger, caps.get("trigger_modes", []),
                   current_text=caps.get("trigger_mode"))
        fill_combo(self._shutter, caps.get("internal_shutter_modes", []),
                   current_text=caps.get("internal_shutter"))
        fill_combo(self._readout, caps.get("readout_rates", []),
                   current_index=caps.get("readout_rate", 0))
        fill_combo(self._preamp, caps.get("preamp_gains", []),
                   current_index=caps.get("preamp_gain", 0))

        em_range = caps.get("em_gain_range")
        supported = em_range is not None
        self._em_gain.setEnabled(supported)
        self._em_btn.setEnabled(supported)
        if supported:
            lo, hi = em_range
            self._em_gain.setRange(int(lo), int(hi))
            if caps.get("em_gain") is not None:
                self._em_gain.blockSignals(True)
                self._em_gain.setValue(int(caps["em_gain"]))
                self._em_gain.blockSignals(False)

    def apply_settings(self, setpoint_c: float, exposure_s: float) -> None:
        self._setpoint.setValue(setpoint_c)
        self._exposure.setValue(exposure_s)

    def setpoint_value(self) -> float:
        return self._setpoint.value()

    def exposure_value(self) -> float:
        return self._exposure.value()

    def update(self, s: dict) -> None:
        self._temp.set_value(f"{s['temperature']:.1f} °C")
        self._status.set_value(s["camera"])
        self._cooler.set_state(_lamp_state(s["cooler_on"]))
        self._stable.set_state(_lamp_state(s["stable"]))
        # Informational only -- "warn" (amber) when not cooled, since you can
        # still acquire, just with higher shot noise.
        self._cooled.set_state("ok" if s.get("cooled") else "warn")
        self._update_progress(s)

    def _update_progress(self, s: dict) -> None:
        frac = s.get("cool_progress", 0.0)
        self._cool_progress.setValue(int(round(100 * frac)))
        if s.get("warming"):
            self._cool_progress.setFormat("warming up… %p%")
        elif s.get("stable") and s.get("cooler_on"):
            self._cool_progress.setFormat("stable")
        elif s.get("cooler_on"):
            self._cool_progress.setFormat("cooling… %p%")
        else:
            self._cool_progress.setFormat("cooler off")


class VacuumPanel(QGroupBox):
    def __init__(self):
        super().__init__("Vacuum")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("vacuum", "Vacuum")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
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
    grating_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__("Grating")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("grating", "Grating")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
        self._position = LabeledValue("Position (steps)")
        self._status = LabeledValue("Status")
        self._homed = StatusLamp("Homed")
        layout.addWidget(self._position)
        layout.addWidget(self._status)
        layout.addWidget(self._homed)

        # Installed-grating selector (declares which grating is in the turret;
        # swaps the calibration). Populated by set_gratings().
        grating_row = QHBoxLayout()
        grating_row.addWidget(QLabel("Grating"))
        self._grating = QComboBox()
        grating_row.addWidget(self._grating, 1)
        layout.addLayout(grating_row)
        self._grating.currentTextChanged.connect(self.grating_changed.emit)

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

    def set_gratings(self, names, current: str | None = None) -> None:
        """Populate the selector (signals blocked so no spurious change)."""
        self._grating.blockSignals(True)
        self._grating.clear()
        for n in names:
            self._grating.addItem(n)
        if current is not None and current in names:
            self._grating.setCurrentText(current)
        self._grating.blockSignals(False)

    def current_grating(self) -> str:
        return self._grating.currentText()

    def update(self, s: dict) -> None:
        self._position.set_value(f"{s['position']:,d}")
        self._status.set_value(s["grating"])
        # Amber (warn) when not homed: moves are refused, but it isn't an error.
        self._homed.set_state("ok" if s.get("homed") else "warn")
        # Go-to-λ needs a homed reference; Home/Stop stay available.
        self._goto_btn.setEnabled(bool(s.get("homed")))
        # Don't allow swapping the declared grating mid-acquisition.
        self._grating.setEnabled(not s.get("busy", False))


class ShutterPanel(QGroupBox):
    """Beam shutter -- independent of the laser, so its own panel."""
    shutter_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__("Shutter")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("shutter", "Shutter")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
        self._lamp = StatusLamp("Shutter")
        layout.addWidget(self._lamp)

        row = QHBoxLayout()
        self._open = QPushButton("Open shutter")
        self._close = QPushButton("Close shutter")
        row.addWidget(self._open)
        row.addWidget(self._close)
        layout.addLayout(row)

        self._open.clicked.connect(lambda: self.shutter_toggled.emit(True))
        self._close.clicked.connect(lambda: self.shutter_toggled.emit(False))

    def update(self, s: dict) -> None:
        self._lamp.set_state("warn" if s["shutter_open"] else "ok")


class LaserPanel(QGroupBox):
    laser_toggled = pyqtSignal(bool)
    power_changed = pyqtSignal(float)
    pulse_picker_changed = pyqtSignal(int)
    rep_rate_changed = pyqtSignal(float)  # Hz

    def __init__(self):
        super().__init__("Laser")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("laser", "Laser")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
        self._lamp = StatusLamp("Laser")
        self._stage = LabeledValue("Emission stage")
        layout.addWidget(self._lamp)
        layout.addWidget(self._stage)

        row = QHBoxLayout()
        self._laser_on = QPushButton("Enable laser")
        self._laser_off = QPushButton("Disable laser")
        row.addWidget(self._laser_on)
        row.addWidget(self._laser_off)
        layout.addLayout(row)

        # --- power / pulse-picker / rep-rate (each: spin + Apply) -----
        grid = QGridLayout()
        self._power = QDoubleSpinBox()
        self._power.setRange(0.0, 100.0)
        self._power.setSuffix(" %")
        self._power_btn = QPushButton("Set power")
        grid.addWidget(self._power, 0, 0)
        grid.addWidget(self._power_btn, 0, 1)

        self._pp = QSpinBox()
        self._pp.setRange(1, 1_000_000)   # 1/1 .. 1/1,000,000
        self._pp.setPrefix("1/")
        self._pp.setValue(1)
        self._pp_btn = QPushButton("Set pulse-picker")
        grid.addWidget(self._pp, 1, 0)
        grid.addWidget(self._pp_btn, 1, 1)

        # Repetition rate is a discrete hardware setting -> dropdown.
        self._rep = QComboBox()
        self._rep_btn = QPushButton("Set rep. rate")
        grid.addWidget(self._rep, 2, 0)
        grid.addWidget(self._rep_btn, 2, 1)
        layout.addLayout(grid)
        self._rep_populated = False

        self._rep_actual = LabeledValue("Actual rep. rate")
        layout.addWidget(self._rep_actual)

        self._laser_on.clicked.connect(lambda: self.laser_toggled.emit(True))
        self._laser_off.clicked.connect(lambda: self.laser_toggled.emit(False))
        self._power_btn.clicked.connect(
            lambda: self.power_changed.emit(self._power.value()))
        self._pp_btn.clicked.connect(
            lambda: self.pulse_picker_changed.emit(self._pp.value()))
        self._rep_btn.clicked.connect(self._emit_rep_rate)

    def _emit_rep_rate(self) -> None:
        hz = self._rep.currentData()
        if hz is not None:
            self.rep_rate_changed.emit(float(hz))

    def _populate_rep_rates(self, rates_hz) -> None:
        self._rep.clear()
        for hz in rates_hz:
            self._rep.addItem(self._fmt_rate(hz), float(hz))
        self._rep_populated = True

    @staticmethod
    def _fmt_rate(hz: float) -> str:
        if hz >= 1e6:
            return f"{hz / 1e6:.3f} MHz"
        if hz >= 1e3:
            return f"{hz / 1e3:.3f} kHz"
        return f"{hz:.1f} Hz"

    def update(self, s: dict) -> None:
        self._lamp.set_state("warn" if s["laser_on"] else "ok")
        self._stage.set_value(s.get("laser_stage", "--"))

        self._power_btn.setEnabled(s.get("laser_supports_power", False))
        self._power.setEnabled(s.get("laser_supports_power", False))

        pp = s.get("laser_pp_ratio")
        self._pp_btn.setEnabled(s.get("laser_supports_pp", False))
        self._pp.setEnabled(s.get("laser_supports_pp", False))

        supports_rep = s.get("laser_supports_rep", False)
        allowed = s.get("laser_allowed_rep_rates")
        if supports_rep and allowed and not self._rep_populated:
            self._populate_rep_rates(allowed)
        self._rep_btn.setEnabled(supports_rep and self._rep_populated)
        self._rep.setEnabled(supports_rep and self._rep_populated)
        rate = s.get("laser_rep_rate")
        self._rep_actual.set_value(
            self._fmt_rate(rate) if rate else ("1/%d" % pp if pp else "--"))


class AcquisitionPanel(QGroupBox):
    single_requested = pyqtSignal()
    scan_requested = pyqtSignal(float, float)
    abort_requested = pyqtSignal()
    record_requested = pyqtSignal()
    live_toggled = pyqtSignal(bool)

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
        self._live_btn = QPushButton("Live")
        self._live_btn.setCheckable(True)
        self._record_btn = QPushButton("Record…")
        self._abort_btn = QPushButton("Abort")
        for b in (self._single_btn, self._scan_btn, self._live_btn,
                  self._record_btn, self._abort_btn):
            row.addWidget(b)
        layout.addLayout(row)

        # Reason shown when acquisition is blocked (e.g. camera not cooled).
        self._hint = QLabel("")
        self._hint.setStyleSheet("color: #c9a227;")
        layout.addWidget(self._hint)

        self._progress = QProgressBar()
        layout.addWidget(self._progress)

        self._busy = False
        self._can_acquire = False
        self._refresh_buttons()

        self._single_btn.clicked.connect(self.single_requested.emit)
        self._scan_btn.clicked.connect(
            lambda: self.scan_requested.emit(self._wl_min.value(),
                                             self._wl_max.value()))
        self._record_btn.clicked.connect(self.record_requested.emit)
        self._live_btn.toggled.connect(self.live_toggled.emit)
        self._abort_btn.clicked.connect(self.abort_requested.emit)

    @property
    def n_frames(self) -> int:
        return self._frames.value()

    def apply_settings(self, wl_min: float, wl_max: float, n_frames: int) -> None:
        self._wl_min.setValue(wl_min)
        self._wl_max.setValue(wl_max)
        self._frames.setValue(n_frames)

    def set_progress(self, done: int, total: int) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        # Single/Scan only when the camera is cooled & ready and we're idle;
        # Abort only while acquiring.
        ready = self._can_acquire and not self._busy
        self._single_btn.setEnabled(ready)
        self._scan_btn.setEnabled(ready)
        self._record_btn.setEnabled(ready)
        # Live can always be stopped while active; otherwise needs an idle bus.
        self._live_btn.setEnabled(self._live_btn.isChecked() or not self._busy)
        self._abort_btn.setEnabled(self._busy)

    @property
    def wl_range(self) -> tuple[float, float]:
        return self._wl_min.value(), self._wl_max.value()

    def set_live(self, on: bool) -> None:
        """Programmatically reflect the live state (e.g. stopped by E-stop)
        without re-emitting ``live_toggled``."""
        self._live_btn.blockSignals(True)
        self._live_btn.setChecked(on)
        self._live_btn.blockSignals(False)
        self._refresh_buttons()
        if self._busy:
            self._hint.setText("")
        elif not self._can_acquire:
            self._hint.setText("Emergency stop active — reset to acquire.")
        else:
            self._hint.setText("")

    def update(self, s: dict) -> None:
        self._can_acquire = s.get("can_acquire", False)
        self._refresh_buttons()
