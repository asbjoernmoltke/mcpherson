"""Hardware worker thread.

All blocking device operations (scans, single grabs, cooldown, warm-up) and
periodic status polling run on a single dedicated QThread, so the GUI thread
never blocks on hardware. The engine's plain callbacks are marshalled to the
GUI thread by emitting Qt signals from this worker (Qt queues them across the
thread boundary).

The E-stop is intentionally *not* routed through this worker's event loop: it
is invoked directly so it stays responsive even while a scan is blocking this
thread. The shutter/laser/grating-stop calls it makes are fast and use
channels independent of the in-progress grating transaction.
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from ..core.exceptions import EStopActive, InterlockError, SpectrometerError
from ..core.system import System
from ..utilities import log


class HardwareWorker(QObject):
    # data / progress (emitted from engine callbacks, queued to GUI thread)
    frame_ready = pyqtSignal(object)
    spectrum_ready = pyqtSignal(object, object)
    progress = pyqtSignal(int, int)
    scan_finished = pyqtSignal()
    scan_aborted = pyqtSignal()

    # status + notifications
    status_updated = pyqtSignal(dict)
    alarm = pyqtSignal(str)
    error = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, system: System):
        super().__init__()
        self.system = system
        self._timer: QTimer | None = None
        self._busy = False

        eng = system.engine
        eng.on_frame = self.frame_ready.emit
        eng.on_spectrum = lambda wl, i: self.spectrum_ready.emit(wl, i)
        eng.on_progress = self.progress.emit
        system.safety.add_alarm_listener(self.alarm.emit)

    # --- status polling (runs in this thread) -------------------------
    @pyqtSlot()
    def start_status_polling(self, interval_ms: int = 500) -> None:
        # Parent the timer to the worker so it shares the worker's thread
        # affinity and is destroyed with it.
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_status)
        self._timer.start(interval_ms)
        self._poll_status()

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop the status timer from within the worker thread (called via a
        blocking queued connection before the thread quits) so Qt never tries
        to kill the timer from another thread."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _poll_status(self) -> None:
        s = self.system
        try:
            s.vacuum.poll()
            s.safety.check_vacuum_while_cold()
            snapshot = {
                "camera": s.camera.status,
                "temperature": s.camera.temperature,
                "cooler_on": s.devices.camera.is_cooler_on(),
                "stable": s.devices.camera.is_temperature_stable(),
                "cooled": s.camera.is_cooled,
                "can_acquire": s.safety.can_acquire,
                "grating": s.grating.status,
                "position": s.grating.position,
                "shutter": s.shutter.status,
                "shutter_open": s.shutter.is_open,
                "laser": s.laser.status,
                "laser_on": s.laser.is_enabled,
                "laser_stage": s.laser.emission_stage,
                "laser_power": s.laser.read_power_percent(),
                "laser_pp_ratio": s.laser.read_pulse_picker_ratio(),
                "laser_rep_rate": s.laser.read_repetition_rate_hz(),
                "laser_supports_power": s.laser.supports_power,
                "laser_supports_pp": s.laser.supports_pulse_picker,
                "laser_supports_rep": s.laser.supports_rep_rate,
                "laser_allowed_rep_rates": s.laser.allowed_rep_rates_hz(),
                "vacuum": s.vacuum.status,
                "vacuum_ok": s.vacuum.vacuum_ok,
                "estopped": s.safety.is_estopped,
                "busy": self._busy,
            }
            self.status_updated.emit(snapshot)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("Status poll failed: %s" % exc)

    # --- long operations (queued slots) -------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    @pyqtSlot(float)
    def do_cooldown(self, setpoint_c: float) -> None:
        try:
            self.system.safety.assert_can_cool()
            self.system.camera.cooldown(setpoint_c)
        except SpectrometerError as exc:
            self.error.emit(str(exc))

    @pyqtSlot()
    def do_warmup(self) -> None:
        self._set_busy(True)
        try:
            self.system.camera.safe_shutdown()
        finally:
            self._set_busy(False)

    @pyqtSlot()
    def do_home(self) -> None:
        self._set_busy(True)
        try:
            self.system.grating.home()
        finally:
            self._set_busy(False)

    @pyqtSlot(float)
    def do_goto_wavelength(self, wavelength_nm: float) -> None:
        self._set_busy(True)
        try:
            self.system.grating.move_to_wavelength(wavelength_nm)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._set_busy(False)

    @pyqtSlot()
    def do_single(self) -> None:
        self._set_busy(True)
        try:
            self.system.engine.single()
        except SpectrometerError as exc:
            self.error.emit(str(exc))
        finally:
            self._set_busy(False)

    @pyqtSlot(float, float)
    def do_scan(self, wl_min: float, wl_max: float) -> None:
        self._set_busy(True)
        try:
            self.system.engine.scan(wl_min, wl_max)
            self.scan_finished.emit()
        except EStopActive:
            self.scan_aborted.emit()
        except SpectrometerError as exc:
            self.error.emit(str(exc))
        finally:
            self._set_busy(False)

    @pyqtSlot(float)
    def set_exposure(self, seconds: float) -> None:
        self.system.camera.configure(exposure_s=seconds)

    @pyqtSlot(bool)
    def set_shutter(self, open_: bool) -> None:
        if open_:
            self.system.shutter.open()
        else:
            self.system.shutter.close()

    @pyqtSlot(bool)
    def set_laser(self, enabled: bool) -> None:
        if enabled:
            self.system.laser.enable()
        else:
            self.system.laser.disable()

    @pyqtSlot(float)
    def set_laser_power(self, percent: float) -> None:
        try:
            self.system.laser.set_power_percent(percent)
        except Exception as exc:
            self.error.emit(str(exc))

    @pyqtSlot(int)
    def set_pulse_picker(self, ratio: int) -> None:
        try:
            self.system.laser.set_pulse_picker_ratio(ratio)
        except Exception as exc:
            self.error.emit(str(exc))

    @pyqtSlot(float)
    def set_rep_rate(self, hz: float) -> None:
        try:
            self.system.laser.set_repetition_rate_hz(hz)
        except Exception as exc:
            self.error.emit(str(exc))
