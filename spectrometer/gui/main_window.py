"""Main application window.

Lays out the control panels (left) and the live preview (centre), owns
*two* hardware worker threads, and wires panel signals to their slots:
``AcquisitionWorker`` (camera + grating + shutter) and ``AuxWorker`` (laser +
vacuum, on independent serial ports -- see ``worker.py``/``aux_worker.py``
for why they're split). The E-stop is connected *directly* to
``SafetyManager.estop`` so it bypasses both worker event loops and fires even
while a scan or home is running.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QMetaObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QMessageBox, QScrollArea,
                             QVBoxLayout, QWidget)

from ..core.system import System
from .estop import EStopButton, SafetyBanner
from .panels.controls import (AcquisitionPanel, CameraPanel, GratingPanel,
                              LaserPanel, ShutterPanel, VacuumPanel)
from .panels.preview import PreviewPanel
from .worker import AcquisitionWorker
from .aux_worker import AuxWorker


class MainWindow(QMainWindow):
    # GUI-thread -> AcquisitionWorker-thread (queued) triggers
    _cooldown = pyqtSignal(float)
    _warmup = pyqtSignal()
    _camera_fan = pyqtSignal(bool)
    _home = pyqtSignal()
    _goto = pyqtSignal(float)
    _grating = pyqtSignal(str)
    _single = pyqtSignal()
    _scan = pyqtSignal(float, float)
    _exposure = pyqtSignal(float)
    _trigger = pyqtSignal(str)
    _internal_shutter = pyqtSignal(str)
    _readout = pyqtSignal(int)
    _preamp = pyqtSignal(int)
    _em_gain = pyqtSignal(int)
    _shutter = pyqtSignal(bool)
    _record = pyqtSignal(object)
    _live = pyqtSignal()
    _connect_dev_acq = pyqtSignal(str)
    _disconnect_dev_acq = pyqtSignal(str)
    _start_polling_acq = pyqtSignal()

    # GUI-thread -> AuxWorker-thread (queued) triggers: laser + vacuum,
    # independent serial ports, split off so they aren't queued behind a
    # blocking camera/grating operation on AcquisitionWorker.
    _turbo = pyqtSignal(bool)
    _backing = pyqtSignal(bool)
    _standby = pyqtSignal(bool)
    _laser = pyqtSignal(bool)
    _laser_listen = pyqtSignal()
    _laser_energy = pyqtSignal(float)
    _pulse_picker = pyqtSignal(int)
    _rep_rate = pyqtSignal(float)
    _connect_dev_aux = pyqtSignal(str)
    _disconnect_dev_aux = pyqtSignal(str)
    _start_polling_aux = pyqtSignal()

    def __init__(self, system: System, settings=None):
        super().__init__()
        self.system = system
        from ..core.settings import Settings
        self.settings = settings if settings is not None else Settings()
        self.setWindowTitle("McPherson Spectrometer")
        self.resize(1800, 950)
        # Set by closeEvent from the shutdown-disposition dialog; read by
        # app.py's run_gui after app.exec() returns to decide whether to
        # warm the camera before releasing it.
        self.leave_equipment_running = False

        # --- panels -----------------------------------------------------
        self.camera_panel = CameraPanel()
        self.vacuum_panel = VacuumPanel()
        self.grating_panel = GratingPanel()
        self.shutter_panel = ShutterPanel()
        self.laser_panel = LaserPanel()
        self.acq_panel = AcquisitionPanel()
        self.preview = PreviewPanel()
        self.banner = SafetyBanner()
        self.estop_btn = EStopButton()
        self._panels = [self.camera_panel, self.vacuum_panel, self.grating_panel,
                        self.shutter_panel, self.laser_panel, self.acq_panel]

        self._build_layout()

        # --- worker threads -----------------------------------------------
        # Acquisition: camera + grating + shutter (must stay serialized with
        # each other -- a scan interleaves grating moves + camera grabs +
        # shutter bracketing).
        self._thread = QThread()
        self.worker = AcquisitionWorker(system)
        self.worker.moveToThread(self._thread)
        self._thread.start()

        # Aux: laser + vacuum, independent serial ports -- own thread so they
        # aren't starved by a blocking home()/capture() on the worker above.
        self._aux_thread = QThread()
        self.aux_worker = AuxWorker(system)
        self.aux_worker.moveToThread(self._aux_thread)
        self._aux_thread.start()

        # Merged status snapshot (see _on_status): both workers' polls feed
        # into this one dict so panels never see a partial snapshot.
        self._status: dict = {}
        self._acq_ready = False
        self._aux_ready = False

        self._connect()
        self._apply_settings()
        self._apply_capabilities()
        self._start_polling_acq.emit()  # queued -> starts AcquisitionWorker's timer
        self._start_polling_aux.emit()  # queued -> starts AuxWorker's timer

    # --- settings <-> UI ----------------------------------------------
    def _apply_settings(self) -> None:
        from ..core.calibration import available_gratings
        s = self.settings
        self.camera_panel.apply_settings(s.cooling_setpoint_c, s.exposure_s)
        self.acq_panel.apply_settings(s.scan_wl_min, s.scan_wl_max, s.n_frames)
        self.grating_panel.set_gratings(available_gratings(), s.grating_name)

    def _apply_capabilities(self) -> None:
        """Populate the camera config dropdowns from the (open) device."""
        try:
            self.camera_panel.set_capabilities(self.system.camera.capabilities())
        except Exception:  # pragma: no cover - device not open / unsupported
            pass

    def _collect_settings(self) -> None:
        s = self.settings
        s.cooling_setpoint_c = self.camera_panel.setpoint_value()
        s.exposure_s = self.camera_panel.exposure_value()
        s.scan_wl_min, s.scan_wl_max = self.acq_panel.wl_range
        s.n_frames = self.acq_panel.n_frames
        s.grating_name = self.grating_panel.current_grating()

    # --- layout --------------------------------------------------------
    def _build_layout(self) -> None:
        # Controls live in TWO columns (the panels are independent), with the
        # safety banner spanning the top and the E-stop spanning the bottom.
        controls = QWidget()
        outer = QVBoxLayout(controls)
        outer.addWidget(self.banner)

        cols = QHBoxLayout()
        col_a = QVBoxLayout()
        for p in (self.camera_panel, self.vacuum_panel, self.grating_panel):
            col_a.addWidget(p)
        col_a.addStretch(1)
        col_b = QVBoxLayout()
        for p in (self.shutter_panel, self.laser_panel, self.acq_panel):
            col_b.addWidget(p)
        col_b.addStretch(1)
        cols.addLayout(col_a)
        cols.addLayout(col_b)
        outer.addLayout(cols)
        outer.addWidget(self.estop_btn)

        scroll = QScrollArea()
        scroll.setWidget(controls)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(820)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        central = QWidget()
        root = QHBoxLayout(central)
        root.addWidget(scroll, stretch=0)
        root.addWidget(self.preview, stretch=1)
        self.setCentralWidget(central)

    # --- signal wiring -------------------------------------------------
    def _connect(self) -> None:
        w = self.worker
        aw = self.aux_worker
        self._acq_panels = [self.camera_panel, self.grating_panel,
                            self.shutter_panel, self.acq_panel]
        self._aux_panels = [self.vacuum_panel, self.laser_panel]

        # GUI -> AcquisitionWorker (queued across threads)
        self._cooldown.connect(w.do_cooldown)
        self._warmup.connect(w.do_warmup)
        self._camera_fan.connect(w.set_camera_fan)
        self._home.connect(w.do_home)
        self._goto.connect(w.do_goto_wavelength)
        self._grating.connect(w.set_grating)
        self._single.connect(w.do_single)
        self._scan.connect(w.do_scan)
        self._exposure.connect(w.set_exposure)
        self._trigger.connect(w.set_trigger_mode)
        self._internal_shutter.connect(w.set_internal_shutter)
        self._readout.connect(w.set_readout_rate)
        self._preamp.connect(w.set_preamp_gain)
        self._em_gain.connect(w.set_em_gain)
        self._shutter.connect(w.set_shutter)
        self._record.connect(w.do_record)
        self._live.connect(w.do_live)
        self._start_polling_acq.connect(w.start_status_polling)

        # GUI -> AuxWorker (queued across threads)
        self._turbo.connect(aw.set_turbo)
        self._backing.connect(aw.set_backing)
        self._standby.connect(aw.set_turbo_standby)
        self._laser.connect(aw.set_laser)
        self._laser_listen.connect(aw.set_laser_listen)
        self._laser_energy.connect(aw.set_laser_energy)
        self._pulse_picker.connect(aw.set_pulse_picker)
        self._rep_rate.connect(aw.set_rep_rate)
        self._start_polling_aux.connect(aw.start_status_polling)

        # panels -> local re-emit (so emission happens on the GUI thread)
        self.camera_panel.cooldown_requested.connect(self._cooldown.emit)
        self.camera_panel.warmup_requested.connect(self._warmup.emit)
        self.camera_panel.fan_toggled.connect(self._camera_fan.emit)
        self.camera_panel.exposure_changed.connect(self._exposure.emit)
        self.camera_panel.trigger_changed.connect(self._trigger.emit)
        self.camera_panel.internal_shutter_changed.connect(self._internal_shutter.emit)
        self.camera_panel.readout_changed.connect(self._readout.emit)
        self.camera_panel.preamp_changed.connect(self._preamp.emit)
        self.camera_panel.em_gain_changed.connect(self._em_gain.emit)
        self.grating_panel.home_requested.connect(self._home.emit)
        self.grating_panel.goto_requested.connect(self._goto.emit)
        self.grating_panel.stop_requested.connect(self._on_grating_stop)
        self.grating_panel.grating_changed.connect(self._grating.emit)
        self.vacuum_panel.turbo_toggled.connect(self._turbo.emit)
        self.vacuum_panel.backing_toggled.connect(self._backing.emit)
        self.vacuum_panel.standby_toggled.connect(self._standby.emit)
        self.shutter_panel.shutter_toggled.connect(self._shutter.emit)
        self.laser_panel.laser_toggled.connect(self._laser.emit)
        self.laser_panel.listen_requested.connect(self._laser_listen.emit)
        self.laser_panel.energy_changed.connect(self._laser_energy.emit)
        self.laser_panel.pulse_picker_changed.connect(self._pulse_picker.emit)
        self.laser_panel.rep_rate_changed.connect(self._rep_rate.emit)
        self.acq_panel.single_requested.connect(self._on_single)
        self.acq_panel.scan_requested.connect(self._on_scan)
        self.acq_panel.abort_requested.connect(self._on_abort)
        self.acq_panel.record_requested.connect(self._on_record)
        self.acq_panel.live_toggled.connect(self._on_live_toggled)

        # per-device connect/disconnect bars, routed to whichever worker
        # owns that device (camera/grating/shutter -> Acquisition;
        # laser/vacuum -> Aux)
        self._connect_dev_acq.connect(w.connect_device)
        self._disconnect_dev_acq.connect(w.disconnect_device)
        self._connect_dev_aux.connect(aw.connect_device)
        self._disconnect_dev_aux.connect(aw.disconnect_device)
        aux_keys = {"laser", "vacuum"}
        self._conn_bars = []
        for p in self._panels:
            for bar in getattr(p, "connection_bars", []):
                self._conn_bars.append(bar)
                if bar.device_key in aux_keys:
                    bar.connect_requested.connect(self._connect_dev_aux.emit)
                    bar.disconnect_requested.connect(self._disconnect_dev_aux.emit)
                else:
                    bar.connect_requested.connect(self._connect_dev_acq.emit)
                    bar.disconnect_requested.connect(self._disconnect_dev_acq.emit)

        # E-stop: direct, not via either worker thread
        self.estop_btn.clicked.connect(self._on_estop)

        # AcquisitionWorker -> GUI
        w.status_updated.connect(lambda s: self._on_status(s, source="acq"))
        w.frame_ready.connect(self.preview.update_frame)
        w.spectrum_ready.connect(self.preview.update_spectrum)
        w.progress.connect(self.acq_panel.set_progress)
        w.busy_changed.connect(self.acq_panel.set_busy)
        w.alarm.connect(self.banner.show_alarm)
        w.error.connect(self._on_error)
        w.scan_aborted.connect(self._on_scan_aborted)
        w.record_finished.connect(self._on_record_finished)
        w.record_aborted.connect(self._on_scan_aborted)
        w.live_stopped.connect(lambda: self.acq_panel.set_live(False))

        # AuxWorker -> GUI
        aw.status_updated.connect(lambda s: self._on_status(s, source="aux"))
        aw.error.connect(self._on_error)

    # --- handlers ------------------------------------------------------
    def _on_status(self, snapshot: dict, *, source: str) -> None:
        """Merge a partial snapshot from either worker into the persistent
        ``self._status`` dict, then refresh only the panels whose owning
        worker has reported at least once. Both workers' polls race
        independently at startup and each only carries its own devices'
        keys, so panels must never see a snapshot missing keys they index
        directly (e.g. ``CameraPanel`` does ``s['temperature']``)."""
        for key in ("connections", "simulated"):
            self._status.setdefault(key, {}).update(snapshot.get(key, {}))
        for key, val in snapshot.items():
            if key not in ("connections", "simulated"):
                self._status[key] = val

        if source == "acq":
            self._acq_ready = True
        else:
            self._aux_ready = True

        conns = self._status.get("connections", {})
        sims = self._status.get("simulated", {})
        for bar in self._conn_bars:
            bar.set_connected(conns.get(bar.device_key, False),
                              sims.get(bar.device_key, False))

        if self._acq_ready:
            for p in self._acq_panels:
                p.update(self._status)
        if self._aux_ready:
            for p in self._aux_panels:
                p.update(self._status)

        if self._status.get("estopped"):
            self.banner.show_alarm("EMERGENCY STOP engaged — reset required.")

    def _on_single(self) -> None:
        self.system.engine.n_frames = self.acq_panel.n_frames
        self._single.emit()

    def _on_scan(self, lo: float, hi: float) -> None:
        self.system.engine.n_frames = self.acq_panel.n_frames
        self._scan.emit(lo, hi)

    def _on_record(self) -> None:
        from .save_dialog import SaveDialog
        wl_min, wl_max = self.acq_panel.wl_range
        dialog = SaveDialog(self, wl_min=wl_min, wl_max=wl_max,
                            settings=self.settings)
        if dialog.exec():
            opts = dialog.options()
            self.settings.update_from_save_options(opts)  # remember choices
            self.system.engine.n_frames = self.acq_panel.n_frames
            self._record.emit(opts)

    def _on_record_finished(self, path: str) -> None:
        QMessageBox.information(self, "Recording complete", "Saved to:\n%s" % path)

    def _on_live_toggled(self, on: bool) -> None:
        if on:
            self._live.emit()           # queued -> worker starts streaming
        else:
            self.worker.stop_live()     # direct -> sets the stop flag

    def _on_abort(self) -> None:
        # Cleanly abort a running scan/recording without latching the E-stop.
        self.system.abort.set()

    def _on_scan_aborted(self) -> None:
        if not self.system.safety.is_estopped:
            self.system.abort.clear()  # ready for the next acquisition

    def _on_grating_stop(self) -> None:
        self.system.grating.stop()  # fast, direct

    def _on_estop(self) -> None:
        self.system.safety.estop()  # direct -> immediate
        self.banner.show_alarm("EMERGENCY STOP engaged — reset required.")

    def _on_error(self, message: str) -> None:
        QMessageBox.warning(self, "Operation refused", message)

    # --- shutdown ------------------------------------------------------
    def _ask_shutdown_disposition(self) -> str | None:
        """Ask what to do with the equipment on close. Returns "safe",
        "leave_running", or None (cancel). Split out from closeEvent so
        tests can stub this instead of blocking on a real modal dialog."""
        box = QMessageBox(self)
        box.setWindowTitle("Close McPherson Spectrometer")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("How should the equipment be left when the GUI closes?")
        box.setInformativeText(
            "Safe shutdown (recommended): warm the camera to a safe "
            "temperature before releasing the connection, then close.\n\n"
            "Leave equipment running: skip the camera warm-up and close "
            "immediately -- the cooler, vacuum pumps, and laser are left "
            "exactly as they are now. Use this to relaunch quickly (e.g. "
            "after an accidental E-stop) without a warm-up/cool-down cycle.")
        safe_btn = box.addButton("Safe Shutdown", QMessageBox.ButtonRole.AcceptRole)
        leave_btn = box.addButton("Leave Running", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(safe_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is safe_btn:
            return "safe"
        if clicked is leave_btn:
            return "leave_running"
        return None

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        # Ask before any teardown, so Cancel leaves the app fully intact
        # (worker threads, timers, live view all untouched).
        disposition = self._ask_shutdown_disposition()
        if disposition is None:
            event.ignore()
            return
        self.leave_equipment_running = (disposition == "leave_running")

        self._collect_settings()   # capture UI values; app.run_gui saves them
        self.worker.stop_live()    # end live view if running
        self.system.abort.set()
        # Stop each status timer inside its own worker thread first, so Qt
        # never tries to kill a timer from another thread on teardown. Ask
        # both to shut down before quitting either, so a slow Acquisition
        # shutdown (e.g. still finishing a blocking op) doesn't delay Aux.
        if self._thread.isRunning():
            QMetaObject.invokeMethod(
                self.worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
        if self._aux_thread.isRunning():
            QMetaObject.invokeMethod(
                self.aux_worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._aux_thread.quit()
        self._thread.wait(2000)
        self._aux_thread.wait(2000)
        super().closeEvent(event)
