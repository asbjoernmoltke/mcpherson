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

import threading
import time

import numpy as np
from PyQt6.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from ..core.exceptions import EStopActive, InterlockError, SpectrometerError
from ..core import storage
from ..core.system import System
from ..utilities import log


class HardwareWorker(QObject):
    # data / progress (emitted from engine callbacks, queued to GUI thread)
    frame_ready = pyqtSignal(object)
    spectrum_ready = pyqtSignal(object, object)
    progress = pyqtSignal(int, int)
    scan_finished = pyqtSignal()
    scan_aborted = pyqtSignal()
    record_finished = pyqtSignal(str)   # output path
    record_aborted = pyqtSignal()
    live_stopped = pyqtSignal()

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
        self._warming = False           # non-blocking warm-up in progress
        self._live_stop = threading.Event()

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
        """Build the status snapshot defensively: each device's section is
        guarded by its connection state so an offline (or failing) device
        reports 'offline' rather than breaking the whole poll."""
        s = self.system
        d = s.devices
        try:
            keys = ("camera", "grating", "shutter", "laser", "vacuum")
            conn = {k: getattr(d, k).is_connected for k in keys}
            # A Dummy stand-in (e.g. the shutter, which has no real driver yet)
            # is flagged 'simulated' so the GUI doesn't show it as real hardware.
            simulated = {k: type(getattr(d, k)).__name__.startswith("Dummy")
                         for k in keys}
            snap = {"connections": conn, "simulated": simulated,
                    "estopped": s.safety.is_estopped,
                    "busy": self._busy, "warming": self._warming}

            # vacuum first (the cooling interlock depends on it)
            if conn["vacuum"]:
                try:
                    s.vacuum.poll()
                    s.safety.check_frost_risk()
                    snap.update(vacuum=s.vacuum.status,
                                frost_point=s.vacuum.frost_point_c,
                                min_safe_setpoint=s.camera.min_safe_setpoint_c(),
                                vacuum_turbo=s.vacuum.turbo_state,
                                vacuum_backing=s.vacuum.backing_state,
                                turbo_running=s.vacuum.turbo_running,
                                backing_running=s.vacuum.backing_running,
                                vacuum_can_control=s.vacuum.supports_control)
                except Exception as exc:
                    log.error("Vacuum poll failed: %s" % exc)
                    snap.update(vacuum="error", frost_point=None,
                                min_safe_setpoint=None, vacuum_turbo=None,
                                vacuum_backing=None, turbo_running=False,
                                backing_running=False, vacuum_can_control=False)
            else:
                snap.update(vacuum="offline", frost_point=None,
                            min_safe_setpoint=None, vacuum_turbo=None,
                            vacuum_backing=None, turbo_running=False,
                            backing_running=False, vacuum_can_control=False)

            if conn["camera"]:
                self._drive_warmup()        # non-blocking warm-up state machine
                snap.update(
                    camera=s.camera.status, temperature=s.camera.temperature,
                    cooler_on=d.camera.is_cooler_on(),
                    stable=d.camera.is_temperature_stable(),
                    cooled=s.camera.is_cooled,
                    cool_progress=s.camera.cooldown_progress())
            else:
                snap.update(camera="offline", temperature=float("nan"),
                            cooler_on=False, stable=False, cooled=False,
                            cool_progress=0.0)
            # acquisition needs the camera connected (and no e-stop/abort)
            snap["can_acquire"] = conn["camera"] and s.safety.can_acquire

            if conn["grating"]:
                snap.update(grating=s.grating.status, position=s.grating.position,
                            homed=s.grating.is_homed)
            else:
                snap.update(grating="offline", position=0, homed=False)

            if conn["shutter"]:
                snap.update(shutter=s.shutter.status, shutter_open=s.shutter.is_open)
            else:
                snap.update(shutter="offline", shutter_open=False)

            if conn["laser"]:
                snap.update(
                    laser=s.laser.status, laser_on=s.laser.is_enabled,
                    laser_stage=s.laser.emission_stage,
                    laser_power=s.laser.read_power_percent(),
                    laser_pp_ratio=s.laser.read_pulse_picker_ratio(),
                    laser_rep_rate=s.laser.read_repetition_rate_hz(),
                    laser_supports_power=s.laser.supports_power,
                    laser_supports_pp=s.laser.supports_pulse_picker,
                    laser_supports_rep=s.laser.supports_rep_rate,
                    laser_allowed_rep_rates=s.laser.allowed_rep_rates_hz())
            else:
                snap.update(
                    laser="offline", laser_on=False, laser_stage="--",
                    laser_power=None, laser_pp_ratio=None, laser_rep_rate=None,
                    laser_supports_power=False, laser_supports_pp=False,
                    laser_supports_rep=False, laser_allowed_rep_rates=None)

            self.status_updated.emit(snap)
        except Exception as exc:  # pragma: no cover - defensive
            log.error("Status poll failed: %s" % exc)

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

    # --- long operations (queued slots) -------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    @pyqtSlot(float)
    def do_cooldown(self, setpoint_c: float) -> None:
        self._warming = False           # a new cooldown cancels any warm-up
        try:
            self.system.safety.assert_can_cool()
            self.system.camera.cooldown(setpoint_c)
        except SpectrometerError as exc:
            self.error.emit(str(exc))

    @pyqtSlot()
    def do_warmup(self) -> None:
        """Begin a controlled warm-up. Non-blocking: the cooler is raised to
        the warm target now and switched off later by ``_drive_warmup`` once
        the sensor is warm, so the GUI/status keep updating throughout."""
        try:
            self.system.camera.begin_warmup()
            self._warming = True
        except Exception as exc:        # pragma: no cover - defensive
            self.error.emit("Warm-up failed to start: %s" % exc)

    def _drive_warmup(self) -> None:
        if not self._warming:
            return
        cam = self.system.camera
        if not self.system.devices.camera.is_cooler_on() or cam.is_warm_enough():
            cam.finish_shutdown()
            self._warming = False

    @pyqtSlot()
    def do_home(self) -> None:
        self._set_busy(True)
        try:
            self.system.grating.home()
        finally:
            self._set_busy(False)

    @pyqtSlot(str)
    def set_grating(self, grating_name: str) -> None:
        """Declare the installed grating -> swap its calibration. Queued to the
        worker thread, so it can't race a running scan (which blocks here)."""
        try:
            self.system.set_grating(grating_name)
        except Exception as exc:
            self.error.emit("Grating change failed: %s" % exc)

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

    # --- live view ----------------------------------------------------
    @pyqtSlot()
    def do_live(self) -> None:
        """Continuous preview: open the shutter, stream the camera's newest
        frame (and its reduced spectrum) until stopped, then close up. Runs on
        the worker thread; ``stop_live`` (called from the GUI thread) ends it,
        as does an E-stop/abort."""
        from ..core.acquisition import reduce_frames
        if self._busy:
            self.error.emit("Busy; stop the current operation first.")
            self.live_stopped.emit()
            return
        self._live_stop.clear()
        self.system.abort.clear()
        self._set_busy(True)
        cam = self.system.camera.driver
        try:
            self.system.shutter.open()
            cam.start_acquisition()
            while not self._live_stop.is_set():
                if self.system.abort.is_set() or self.system.safety.is_estopped:
                    break
                img = cam.read_newest_image()
                if img is not None:
                    self.frame_ready.emit(img)
                    wl = self.system.calibration.wavelength_axis(
                        self.system.grating.position)
                    self.spectrum_ready.emit(wl, reduce_frames(img))
                self._live_stop.wait(0.03)   # ~30 fps, interruptible
        except Exception as exc:
            self.error.emit("Live view failed: %s" % exc)
        finally:
            try:
                cam.stop_acquisition()
            except Exception:  # pragma: no cover
                pass
            self.system.shutter.close()
            self._set_busy(False)
            self.live_stopped.emit()

    def stop_live(self) -> None:
        """Stop live view. Plain method (not a slot) so the GUI thread can set
        the flag while the worker thread is busy in the live loop."""
        self._live_stop.set()

    # --- recording (data saving) --------------------------------------
    @pyqtSlot(object)
    def do_record(self, opts: storage.SaveOptions) -> None:
        self._set_busy(True)
        self.system.abort.clear()       # fresh run
        try:
            path = self._run_recording(opts)
            self.record_finished.emit(path)
        except EStopActive:
            self.record_aborted.emit()
        except SpectrometerError as exc:
            self.error.emit(str(exc))
        except Exception as exc:        # storage/io errors
            self.error.emit("Recording failed: %s" % exc)
        finally:
            self._set_busy(False)

    def _run_recording(self, opts: storage.SaveOptions) -> str:
        if not opts.content_selected():
            raise SpectrometerError("Nothing selected to save (tick image / "
                                    "spectrum / stitched).")
        run_meta = storage.collect_metadata(self.system) if opts.save_metadata else {}
        fmt = opts.resolved_format()
        base = opts.base_path()
        if opts.record_type == "frames":
            return self._record_frames(opts, run_meta, fmt, base)
        return self._record_scans(opts, run_meta, fmt, base)

    def _abort_check(self) -> None:
        if self.system.abort.is_set() or self.system.safety.is_estopped:
            raise EStopActive("Recording aborted.")

    # --- scans: per-scan writer honours the a/b/c content flags --------
    def _record_scans(self, opts, run_meta, fmt, base) -> str:
        if fmt == "hdf5":
            path = base + ".h5"
            rec = storage.Hdf5Recorder(path, run_meta, opts.save_metadata)
            try:
                self._scan_series(opts, _Hdf5ScanWriter(rec, opts))
            finally:
                rec.close()
            return path
        # CSV (no 2-D images): stitched and/or per-shot 1-D spectra.
        if opts.save_metadata and run_meta:
            storage.write_metadata_sidecar(base + ".csv", run_meta)
        self._scan_series(opts, _CsvScanWriter(opts, base))
        return (base + ".csv") if opts.is_single() else (base + "_*.csv")

    def _scan_series(self, opts, writer) -> None:
        eng = self.system.engine
        deadline = (time.monotonic() + opts.stop_duration_s
                    if opts.stop_mode == "duration" else None)
        i = 0
        while True:
            self._abort_check()
            if opts.stop_mode == "count" and i >= opts.stop_count:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            writer.begin_scan(i)
            eng.on_shot = writer.on_shot          # capture per-shot data
            try:
                grid, stitched = eng.scan(opts.wl_min, opts.wl_max)
            finally:
                eng.on_shot = None
            writer.end_scan(i, grid, stitched)
            i += 1
            self.progress.emit(i, opts.stop_count if opts.stop_mode == "count" else 0)

    # --- frames: time-series of shots at the current position ----------
    def _record_frames(self, opts, run_meta, fmt, base) -> str:
        from ..core.acquisition import average_frames, reduce_frames
        cal = self.system.calibration
        sync = self.system.sync
        n = self.system.engine.n_frames
        csv = (fmt == "csv")
        rec = None if csv else storage.Hdf5Recorder(path := base + ".h5",
                                                    run_meta, opts.save_metadata)
        if csv and opts.save_metadata and run_meta:
            storage.write_metadata_sidecar(base + ".csv", run_meta)
        try:
            k = saved = 0
            while True:
                self._abort_check()
                frames = sync.acquire(n)
                keep = (k % max(1, opts.cadence_n) == 0
                        if opts.cadence_mode == "every_nth" else True)
                if keep:
                    pos = self.system.grating.position
                    wl = cal.wavelength_axis(pos)
                    image = average_frames(frames)
                    spectrum = reduce_frames(frames)
                    meta = {"index": saved, "position": pos,
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    if csv:                       # spectrum only (no 2-D in CSV)
                        if opts.save_spectrum_1d:
                            storage.write_spectrum_csv(
                                "%s_%04d.csv" % (base, saved), wl, spectrum)
                    else:
                        rec.append_frame(
                            image=image if opts.save_image_2d else None,
                            spectrum=spectrum if opts.save_spectrum_1d else None,
                            wavelength=wl, item_meta=meta)
                    self.frame_ready.emit(frames[-1] if frames.ndim == 3 else frames)
                    saved += 1
                    self.progress.emit(saved, 0)   # indeterminate
                k += 1
                if opts.cadence_mode == "every_interval":
                    if self.system.abort.wait(opts.cadence_interval_s):
                        raise EStopActive("Recording aborted.")
        finally:
            if rec is not None:
                rec.close()
        return (base + ".h5") if not csv else (base + "_*.csv")

    @pyqtSlot(float)
    def set_exposure(self, seconds: float) -> None:
        self.system.camera.configure(exposure_s=seconds)

    @pyqtSlot(str)
    def set_trigger_mode(self, mode: str) -> None:
        try:
            self.system.camera.configure(trigger_mode=mode)
        except Exception as exc:
            self.error.emit("Trigger mode failed: %s" % exc)

    @pyqtSlot(str)
    def set_internal_shutter(self, mode: str) -> None:
        try:
            self.system.camera.configure(internal_shutter=mode)
        except Exception as exc:
            self.error.emit("Internal shutter failed: %s" % exc)

    @pyqtSlot(int)
    def set_readout_rate(self, index: int) -> None:
        try:
            self.system.camera.configure(readout_index=index)
        except Exception as exc:
            self.error.emit("Readout rate failed: %s" % exc)

    @pyqtSlot(int)
    def set_preamp_gain(self, index: int) -> None:
        try:
            self.system.camera.configure(preamp_index=index)
        except Exception as exc:
            self.error.emit("Pre-amp gain failed: %s" % exc)

    @pyqtSlot(int)
    def set_em_gain(self, value: int) -> None:
        try:
            self.system.camera.configure(em_gain=value)
        except Exception as exc:
            self.error.emit("EM gain failed: %s" % exc)

    @pyqtSlot(bool)
    def set_turbo(self, on: bool) -> None:
        v = self.system.vacuum
        try:
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


# --- per-scan writers: translate the a/b/c content flags to storage calls ---
class _Hdf5ScanWriter:
    """Writes a scan's per-shot data and/or stitched spectrum to HDF5."""

    def __init__(self, recorder: storage.Hdf5Recorder, opts: storage.SaveOptions):
        self.rec = recorder
        self.opts = opts
        self._sg = None

    def begin_scan(self, i: int) -> None:
        self._sg = self.rec.new_scan(
            {"scan_index": i, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def on_shot(self, shot_index, position, image, wavelength, intensity) -> None:
        if not (self.opts.save_image_2d or self.opts.save_spectrum_1d):
            return
        self._sg.add_shot(
            image=image if self.opts.save_image_2d else None,
            spectrum=intensity if self.opts.save_spectrum_1d else None,
            wavelength=wavelength,
            item_meta={"shot_index": shot_index, "position": position})

    def end_scan(self, i, grid, stitched) -> None:
        if self.opts.save_stitched:
            self._sg.set_stitched(grid, stitched)


class _CsvScanWriter:
    """Writes a scan's stitched and/or per-shot 1-D spectra as CSV files
    (no 2-D images -- those force HDF5)."""

    def __init__(self, opts: storage.SaveOptions, base: str):
        self.opts = opts
        self.base = base
        self._i = 0

    def begin_scan(self, i: int) -> None:
        self._i = i

    def on_shot(self, shot_index, position, image, wavelength, intensity) -> None:
        if self.opts.save_spectrum_1d:
            storage.write_spectrum_csv(
                "%s_scan%04d_shot%04d.csv" % (self.base, self._i, shot_index),
                wavelength, intensity)

    def end_scan(self, i, grid, stitched) -> None:
        if self.opts.save_stitched:
            name = ((self.base + ".csv") if self.opts.is_single()
                    else "%s_%04d.csv" % (self.base, i))
            storage.write_spectrum_csv(name, grid, stitched)
