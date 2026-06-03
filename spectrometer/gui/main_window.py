"""Main application window.

Lays out the control panels (left) and the live preview (centre), owns the
hardware worker thread, and wires panel signals to worker slots. The E-stop
is connected *directly* to ``SafetyManager.estop`` so it bypasses the worker
event loop and fires even while a scan is running.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QMetaObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QMainWindow, QMessageBox, QScrollArea,
                             QVBoxLayout, QWidget)

from ..core.system import System
from .estop import EStopButton, SafetyBanner
from .panels.controls import (AcquisitionPanel, CameraPanel, GratingPanel,
                              ShutterLaserPanel, VacuumPanel)
from .panels.preview import PreviewPanel
from .worker import HardwareWorker


class MainWindow(QMainWindow):
    # GUI-thread -> worker-thread (queued) triggers
    _cooldown = pyqtSignal(float)
    _warmup = pyqtSignal()
    _home = pyqtSignal()
    _goto = pyqtSignal(float)
    _single = pyqtSignal()
    _scan = pyqtSignal(float, float)
    _exposure = pyqtSignal(float)
    _shutter = pyqtSignal(bool)
    _laser = pyqtSignal(bool)
    _laser_power = pyqtSignal(float)
    _pulse_picker = pyqtSignal(int)
    _rep_rate = pyqtSignal(float)
    _start_polling = pyqtSignal()

    def __init__(self, system: System):
        super().__init__()
        self.system = system
        self.setWindowTitle("McPherson Spectrometer")
        self.resize(1500, 950)

        # --- panels -----------------------------------------------------
        self.camera_panel = CameraPanel()
        self.vacuum_panel = VacuumPanel()
        self.grating_panel = GratingPanel()
        self.shutter_laser_panel = ShutterLaserPanel()
        self.acq_panel = AcquisitionPanel()
        self.preview = PreviewPanel()
        self.banner = SafetyBanner()
        self.estop_btn = EStopButton()
        self._panels = [self.camera_panel, self.vacuum_panel, self.grating_panel,
                        self.shutter_laser_panel, self.acq_panel]

        self._build_layout()

        # --- worker thread ----------------------------------------------
        self._thread = QThread()
        self.worker = HardwareWorker(system)
        self.worker.moveToThread(self._thread)
        self._thread.start()

        self._connect()
        self._start_polling.emit()  # queued -> starts the worker's status timer

    # --- layout --------------------------------------------------------
    def _build_layout(self) -> None:
        controls = QWidget()
        cl = QVBoxLayout(controls)
        cl.addWidget(self.banner)
        for p in self._panels:
            cl.addWidget(p)
        cl.addStretch(1)
        cl.addWidget(self.estop_btn)

        scroll = QScrollArea()
        scroll.setWidget(controls)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        central = QWidget()
        root = QHBoxLayout(central)
        root.addWidget(scroll, stretch=0)
        root.addWidget(self.preview, stretch=1)
        self.setCentralWidget(central)

    # --- signal wiring -------------------------------------------------
    def _connect(self) -> None:
        w = self.worker

        # GUI -> worker (queued across threads)
        self._cooldown.connect(w.do_cooldown)
        self._warmup.connect(w.do_warmup)
        self._home.connect(w.do_home)
        self._goto.connect(w.do_goto_wavelength)
        self._single.connect(w.do_single)
        self._scan.connect(w.do_scan)
        self._exposure.connect(w.set_exposure)
        self._shutter.connect(w.set_shutter)
        self._laser.connect(w.set_laser)
        self._laser_power.connect(w.set_laser_power)
        self._pulse_picker.connect(w.set_pulse_picker)
        self._rep_rate.connect(w.set_rep_rate)
        self._start_polling.connect(w.start_status_polling)

        # panels -> local re-emit (so emission happens on the GUI thread)
        self.camera_panel.cooldown_requested.connect(self._cooldown.emit)
        self.camera_panel.warmup_requested.connect(self._warmup.emit)
        self.camera_panel.exposure_changed.connect(self._exposure.emit)
        self.grating_panel.home_requested.connect(self._home.emit)
        self.grating_panel.goto_requested.connect(self._goto.emit)
        self.grating_panel.stop_requested.connect(self._on_grating_stop)
        self.shutter_laser_panel.shutter_toggled.connect(self._shutter.emit)
        self.shutter_laser_panel.laser_toggled.connect(self._laser.emit)
        self.shutter_laser_panel.power_changed.connect(self._laser_power.emit)
        self.shutter_laser_panel.pulse_picker_changed.connect(self._pulse_picker.emit)
        self.shutter_laser_panel.rep_rate_changed.connect(self._rep_rate.emit)
        self.acq_panel.single_requested.connect(self._on_single)
        self.acq_panel.scan_requested.connect(self._on_scan)
        self.acq_panel.abort_requested.connect(self._on_abort)

        # E-stop: direct, not via worker thread
        self.estop_btn.clicked.connect(self._on_estop)

        # worker -> GUI
        w.status_updated.connect(self._on_status)
        w.frame_ready.connect(self.preview.update_frame)
        w.spectrum_ready.connect(self.preview.update_spectrum)
        w.progress.connect(self.acq_panel.set_progress)
        w.busy_changed.connect(self.acq_panel.set_busy)
        w.alarm.connect(self.banner.show_alarm)
        w.error.connect(self._on_error)
        w.scan_aborted.connect(self._on_scan_aborted)

    # --- handlers ------------------------------------------------------
    def _on_status(self, snapshot: dict) -> None:
        for p in self._panels:
            p.update(snapshot)
        if snapshot["estopped"]:
            self.banner.show_alarm("EMERGENCY STOP engaged — reset required.")

    def _on_single(self) -> None:
        self.system.engine.n_frames = self.acq_panel.n_frames
        self._single.emit()

    def _on_scan(self, lo: float, hi: float) -> None:
        self.system.engine.n_frames = self.acq_panel.n_frames
        self._scan.emit(lo, hi)

    def _on_abort(self) -> None:
        # Cleanly abort a running scan without latching the full E-stop.
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
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt signature)
        self.system.abort.set()
        # Stop the status timer inside the worker thread first, so Qt never
        # tries to kill a timer from another thread on teardown.
        if self._thread.isRunning():
            QMetaObject.invokeMethod(
                self.worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(2000)
        super().closeEvent(event)
