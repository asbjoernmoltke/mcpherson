"""Auxiliary worker thread: laser + vacuum gauge.

These two devices sit on independent serial ports (laser CLI, Edwards TIC)
with no coupling to the camera/grating/shutter acquisition path, so they get
their own dedicated QThread rather than sharing ``AcquisitionWorker``'s. That
keeps laser commands and the (safety-relevant) vacuum reading responsive even
while a long ``do_home``/``do_scan`` is blocking the acquisition thread --
see ``worker.py`` for the full rationale.

``assert_can_stop_pumping`` (reached from ``set_turbo``/``set_turbo_standby``)
needs to know whether the camera is cold, but the camera driver is
thread-confined to ``AcquisitionWorker``. It reads
``CameraController.is_cold_cached`` instead of the live driver state; that
cache is refreshed once per ``AcquisitionWorker`` poll cycle (<=500ms
staleness), which is an accepted trade-off against a minutes-long thermal
process.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from ..core.system import System
from ..utilities import log


class AuxWorker(QObject):
    status_updated = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, system: System):
        super().__init__()
        self.system = system
        self._timer: QTimer | None = None

    # --- status polling (runs in this thread) -------------------------
    @pyqtSlot()
    def start_status_polling(self, interval_ms: int = 500) -> None:
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_status)
        self._timer.start(interval_ms)
        self._poll_status()

    @pyqtSlot()
    def shutdown(self) -> None:
        """Stop the status timer from within this thread (called via a
        blocking queued connection before the thread quits) so Qt never tries
        to kill the timer from another thread."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _poll_status(self) -> None:
        """Laser + vacuum status only -- see ``AcquisitionWorker._poll_status``
        for camera/grating/shutter, polled independently on the other thread."""
        s = self.system
        d = s.devices
        try:
            keys = ("laser", "vacuum")
            conn = {k: getattr(d, k).is_connected for k in keys}
            simulated = {k: type(getattr(d, k)).__name__.startswith("Dummy")
                         for k in keys}
            snap = {"connections": conn, "simulated": simulated,
                    "estopped": s.safety.is_estopped}

            if conn["vacuum"]:
                try:
                    s.vacuum.poll()
                    alerts = s.safety.check_pump_health()
                    snap.update(vacuum=s.vacuum.status,
                                frost_point=s.vacuum.frost_point_c,
                                min_safe_setpoint=s.camera.min_safe_setpoint_c(),
                                vacuum_turbo=s.vacuum.turbo_state,
                                vacuum_backing=s.vacuum.backing_state,
                                turbo_running=s.vacuum.turbo_running,
                                backing_running=s.vacuum.backing_running,
                                turbo_standby=s.vacuum.turbo_standby,
                                vacuum_alerts=alerts,
                                vacuum_can_control=s.vacuum.supports_control)
                except Exception as exc:
                    log.error("Vacuum poll failed: %s" % exc)
                    snap.update(vacuum="error", frost_point=None,
                                min_safe_setpoint=None, vacuum_turbo=None,
                                vacuum_backing=None, turbo_running=False,
                                backing_running=False, turbo_standby=False,
                                vacuum_alerts=["Vacuum poll failed"],
                                vacuum_can_control=False)
            else:
                snap.update(vacuum="offline", frost_point=None,
                            min_safe_setpoint=None, vacuum_turbo=None,
                            vacuum_backing=None, turbo_running=False,
                            backing_running=False, turbo_standby=False,
                            vacuum_alerts=[], vacuum_can_control=False)

            if conn["laser"]:
                snap.update(
                    laser=s.laser.status, laser_on=s.laser.is_enabled,
                    laser_stage=s.laser.emission_stage,
                    laser_state=s.laser.emission_state,
                    laser_supports_listen=s.laser.supports_listen,
                    laser_power=s.laser.read_power_percent(),
                    laser_energy=s.laser.read_pulse_energy_uj(),
                    laser_energy_measured=s.laser.read_measured_pulse_energy_uj(),
                    laser_energy_max=s.laser.max_pulse_energy_uj,
                    laser_supports_energy=s.laser.supports_energy,
                    laser_pp_ratio=s.laser.read_pulse_picker_ratio(),
                    laser_rep_rate=s.laser.read_repetition_rate_hz(),
                    laser_supports_power=s.laser.supports_power,
                    laser_supports_pp=s.laser.supports_pulse_picker,
                    laser_supports_rep=s.laser.supports_rep_rate,
                    laser_allowed_rep_rates=s.laser.allowed_rep_rates_hz())
            else:
                snap.update(
                    laser="offline", laser_on=False, laser_stage="--",
                    laser_state="--", laser_supports_listen=False,
                    laser_power=None, laser_energy=None,
                    laser_energy_measured=None, laser_energy_max=None,
                    laser_supports_energy=False,
                    laser_pp_ratio=None, laser_rep_rate=None,
                    laser_supports_power=False, laser_supports_pp=False,
                    laser_supports_rep=False, laser_allowed_rep_rates=None)

            self.status_updated.emit(snap)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("Aux status poll failed: %s" % exc)

    # --- connection management ----------------------------------------
    @pyqtSlot(str)
    def connect_device(self, key: str) -> None:
        dev = getattr(self.system.devices, key, None)
        if dev is None:
            self.error.emit("Unknown device: %s" % key)
            return
        try:
            dev.open()
        except Exception as exc:
            self.error.emit("Connect %s failed: %s" % (key, exc))
        self._poll_status()

    @pyqtSlot(str)
    def disconnect_device(self, key: str) -> None:
        dev = getattr(self.system.devices, key, None)
        if dev is None:
            self.error.emit("Unknown device: %s" % key)
            return
        try:
            dev.close()
        except Exception as exc:
            self.error.emit("Disconnect %s failed: %s" % (key, exc))
        self._poll_status()

    # --- vacuum pump control --------------------------------------------
    @pyqtSlot(bool)
    def set_turbo(self, on: bool) -> None:
        v = self.system.vacuum
        try:
            if not on:
                # Stopping the turbo auto-vents -- block while the camera is cold.
                self.system.safety.assert_can_stop_pumping()
            (v.turbo_on if on else v.turbo_off)()
        except Exception as exc:
            self.error.emit(str(exc))
        self._poll_status()

    @pyqtSlot(bool)
    def set_backing(self, on: bool) -> None:
        v = self.system.vacuum
        try:
            (v.backing_on if on else v.backing_off)()
        except Exception as exc:
            self.error.emit(str(exc))
        self._poll_status()

    @pyqtSlot(bool)
    def set_turbo_standby(self, on: bool) -> None:
        v = self.system.vacuum
        try:
            if on:
                # Standby lets pressure drift up -- block while the camera is cold.
                self.system.safety.assert_can_stop_pumping()
            (v.turbo_standby_on if on else v.turbo_standby_off)()
        except Exception as exc:
            self.error.emit(str(exc))
        self._poll_status()

    # --- laser ----------------------------------------------------------
    @pyqtSlot(bool)
    def set_laser(self, enabled: bool) -> None:
        if enabled:
            self.system.laser.enable()
        else:
            self.system.laser.disable()

    @pyqtSlot()
    def set_laser_listen(self) -> None:
        try:
            self.system.laser.listen()
        except Exception as exc:
            self.error.emit(str(exc))

    @pyqtSlot(float)
    def set_laser_energy(self, energy_uj: float) -> None:
        try:
            self.system.laser.set_pulse_energy_uj(energy_uj)
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
