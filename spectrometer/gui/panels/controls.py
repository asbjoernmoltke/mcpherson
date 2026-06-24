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
        self._setpoint.setRange(-50.0, -20.0)   # DU920P_BEN settable min is -50 C (air-cooled)
        self._setpoint.setValue(-45.0)          # in-range default
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
    turbo_toggled = pyqtSignal(bool)
    backing_toggled = pyqtSignal(bool)
    standby_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__("Vacuum")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("vacuum", "Vacuum")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
        self._pressure = LabeledValue("Pressure")
        # Frost point + the coldest setpoint the camera may cool to right now
        # (frost point + margin) -- both fall as the chamber pumps down.
        self._frost = LabeledValue("Frost point")
        self._min_safe = LabeledValue("Min safe setpoint")
        self._turbo = LabeledValue("Turbo pump")
        self._backing = LabeledValue("Backing pump")
        # Dedicated fault field: controller alerts (over-temp/over-pressure) and
        # the turbo-without-backing condition. Turns red when something is wrong.
        self._alerts = LabeledValue("Alerts", "None")
        for w in (self._pressure, self._frost, self._min_safe, self._turbo,
                  self._backing, self._alerts):
            layout.addWidget(w)

        # Pump control. The turbo can't start until the backing pump is running;
        # the backing can't stop until the turbo is stopped (the controller
        # enforces both -- the buttons just reflect it).
        brow = QHBoxLayout()
        self._backing_on = QPushButton("Backing start")
        self._backing_off = QPushButton("Backing stop")
        brow.addWidget(self._backing_on)
        brow.addWidget(self._backing_off)
        layout.addLayout(brow)
        trow = QHBoxLayout()
        self._turbo_on = QPushButton("Turbo start")
        self._turbo_off = QPushButton("Turbo stop")
        trow.addWidget(self._turbo_on)
        trow.addWidget(self._turbo_off)
        layout.addLayout(trow)
        # Gentle spin-down: standby holds the turbo at reduced speed without
        # stopping it -- stays under vacuum and (auto-vent 'On stop') won't vent.
        self._standby = QPushButton("Turbo standby")
        self._standby.setCheckable(True)
        self._standby.setToolTip(
            "Hold the turbo at reduced speed (no vent). Uncheck for full speed.")
        layout.addWidget(self._standby)

        self._backing_on.clicked.connect(lambda: self.backing_toggled.emit(True))
        self._backing_off.clicked.connect(lambda: self.backing_toggled.emit(False))
        self._turbo_on.clicked.connect(lambda: self.turbo_toggled.emit(True))
        self._turbo_off.clicked.connect(lambda: self.turbo_toggled.emit(False))
        self._standby.clicked.connect(lambda checked: self.standby_toggled.emit(checked))

    @staticmethod
    def _fmt_temp(v) -> str:
        if v is None:
            return "--"
        return "%.0f °C" % v if v < 100.0 else "— (too warm)"

    def update(self, s: dict) -> None:
        self._pressure.set_value(s["vacuum"])
        self._frost.set_value(self._fmt_temp(s.get("frost_point")))
        self._min_safe.set_value(self._fmt_temp(s.get("min_safe_setpoint")))
        self._turbo.set_value(s.get("vacuum_turbo") or "--")
        self._backing.set_value(s.get("vacuum_backing") or "--")
        alerts = s.get("vacuum_alerts") or []
        self._alerts.set_value("; ".join(alerts) if alerts else "None",
                               alert=bool(alerts))

        can = s.get("vacuum_can_control", False)
        turbo_run = s.get("turbo_running", False)
        backing_run = s.get("backing_running", False)
        self._backing_on.setEnabled(can and not backing_run)
        self._backing_off.setEnabled(can and backing_run and not turbo_run)
        self._turbo_on.setEnabled(can and backing_run and not turbo_run)
        self._turbo_off.setEnabled(can and turbo_run)
        # Standby only while the turbo is spinning; reflect the live state
        # (setChecked doesn't fire 'clicked', so no command is emitted here).
        self._standby.setEnabled(can and turbo_run)
        self._standby.setChecked(bool(s.get("turbo_standby", False)))


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

        row = QHBoxLayout()
        self._open = QPushButton("Open shutter")
        self._close = QPushButton("Close shutter")
        row.addWidget(self._open)
        row.addWidget(self._close)
        layout.addLayout(row)

        self._open.clicked.connect(lambda: self.shutter_toggled.emit(True))
        self._close.clicked.connect(lambda: self.shutter_toggled.emit(False))

    def update(self, s: dict) -> None:
        # Open/closed is shown by which button is active (no separate lamp).
        is_open = bool(s.get("shutter_open", False))
        self._open.setEnabled(not is_open)
        self._close.setEnabled(is_open)


class LaserPanel(QGroupBox):
    laser_toggled = pyqtSignal(bool)
    listen_requested = pyqtSignal()
    energy_changed = pyqtSignal(float)    # pulse energy setpoint, µJ
    pulse_picker_changed = pyqtSignal(int)
    rep_rate_changed = pyqtSignal(float)  # Hz

    def __init__(self):
        super().__init__("Laser")
        layout = QVBoxLayout(self)
        self.conn = ConnectionBar("laser", "Laser")
        self.connection_bars = [self.conn]
        layout.addWidget(self.conn)
        self._stage = LabeledValue("State")
        layout.addWidget(self._stage)

        row = QHBoxLayout()
        self._laser_on = QPushButton("Enable laser")
        self._laser_listen = QPushButton("Listen")
        self._laser_off = QPushButton("Disable laser")
        row.addWidget(self._laser_on)
        row.addWidget(self._laser_listen)
        row.addWidget(self._laser_off)
        layout.addLayout(row)

        # --- energy / pulse-picker / rep-rate (each: spin + Apply) -----
        grid = QGridLayout()
        self._energy = QDoubleSpinBox()
        self._energy.setRange(0.0, 40.0)      # rescaled from laser_energy_max
        self._energy.setDecimals(2)
        self._energy.setSingleStep(0.1)
        self._energy.setSuffix(" µJ")
        self._energy_btn = QPushButton("Set energy")
        grid.addWidget(self._energy, 0, 0)
        grid.addWidget(self._energy_btn, 0, 1)

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
        self._inputs_synced = False   # one-time sync of input boxes per connect

        self._energy_measured = LabeledValue("Measured energy")
        self._rep_actual = LabeledValue("Actual rep. rate")
        self._power_req = LabeledValue("Requested avg. power")
        layout.addWidget(self._energy_measured)
        layout.addWidget(self._rep_actual)
        layout.addWidget(self._power_req)

        self._laser_on.clicked.connect(lambda: self.laser_toggled.emit(True))
        self._laser_off.clicked.connect(lambda: self.laser_toggled.emit(False))
        self._laser_listen.clicked.connect(self.listen_requested.emit)
        self._energy_btn.clicked.connect(
            lambda: self.energy_changed.emit(self._energy.value()))
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

    @staticmethod
    def _fmt_power(watts: float) -> str:
        if watts >= 1.0:
            return f"{watts:.2f} W"
        if watts >= 1e-3:
            return f"{watts * 1e3:.1f} mW"
        return f"{watts * 1e6:.0f} µW"

    def update(self, s: dict) -> None:
        self._stage.set_value(s.get("laser_state", "--"))
        self._laser_listen.setEnabled(s.get("laser_supports_listen", False))

        supports_energy = s.get("laser_supports_energy", False)
        self._energy_btn.setEnabled(supports_energy)
        self._energy.setEnabled(supports_energy)
        emax = s.get("laser_energy_max")
        if emax and abs(self._energy.maximum() - emax) > 1e-9:
            self._energy.setRange(0.0, float(emax))
        meas = s.get("laser_energy_measured")
        self._energy_measured.set_value(
            "%.2f µJ" % meas if meas is not None else "--")

        pp = s.get("laser_pp_ratio")
        self._pp_btn.setEnabled(s.get("laser_supports_pp", False))
        self._pp.setEnabled(s.get("laser_supports_pp", False))

        supports_rep = s.get("laser_supports_rep", False)
        allowed = s.get("laser_allowed_rep_rates")
        if supports_rep and allowed and not self._rep_populated:
            self._populate_rep_rates(allowed)
        self._rep_btn.setEnabled(supports_rep and self._rep_populated)
        self._rep.setEnabled(supports_rep and self._rep_populated)
        # Actual output rep rate = base (seed) rate / pulse-picker ratio. The
        # picker "1/N" divides the seed rate, so output = rate / N (CLI reports
        # the seed rate in e_freq; the picker is separate in e_div).
        rate = s.get("laser_rep_rate")
        ratio = pp if pp else 1
        actual_hz = (rate / ratio) if rate else None
        self._rep_actual.set_value(
            self._fmt_rate(actual_hz) if actual_hz else "--")

        # Requested average power = energy setpoint x actual output rep rate.
        energy = s.get("laser_energy")
        if energy is not None and actual_hz:
            self._power_req.set_value(self._fmt_power(energy * 1e-6 * actual_hz))
        else:
            self._power_req.set_value("--")

        self._sync_inputs(s)

    def _sync_inputs(self, s: dict) -> None:
        """Once per connect, snap the input boxes to the laser's actual values
        so the controls reflect the running laser (e.g. the rep-rate dropdown
        shows the real 100 kHz, not the default). Skipped for any box the user
        is currently editing; reset when the laser goes offline."""
        online = s.get("laser") not in (None, "offline", "error")
        if not online:
            self._inputs_synced = False
            return
        rep_ready = (not s.get("laser_supports_rep", False)) or self._rep_populated
        if self._inputs_synced or not rep_ready:
            return
        energy = s.get("laser_energy")
        if energy is not None and not self._energy.hasFocus():
            self._energy.setValue(float(energy))
        pp = s.get("laser_pp_ratio")
        if pp is not None and not self._pp.hasFocus():
            self._pp.setValue(int(pp))
        rate = s.get("laser_rep_rate")
        if rate is not None and self._rep_populated and not self._rep.hasFocus():
            idx = self._rep.findData(float(rate))
            if idx >= 0:
                self._rep.setCurrentIndex(idx)
        self._inputs_synced = True


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
