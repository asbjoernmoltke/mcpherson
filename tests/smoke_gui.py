"""Headless GUI smoke test (run with QT_QPA_PLATFORM=offscreen).

Builds the real MainWindow on dummy devices, drives a cooldown -> single ->
scan -> e-stop sequence through the actual Qt signal/worker plumbing, and
checks that frames/spectra/progress signals arrive. Not a pytest (needs a Qt
event loop); invoked directly by the test runner command.
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from spectrometer.core.system import build_system
from spectrometer.gui.main_window import MainWindow

results = {"frames": 0, "spectra": 0, "progress": 0, "errors": []}


def main() -> int:
    system = build_system(dummy=True, cooling_threshold=1.0e-4)
    system.open_all()
    # allow cooling + force the dummy camera cold/stable for can_acquire
    system.devices.vacuum.set_pressure(1.0e-6)
    system.devices.camera.set_temperature(-60.0)
    system.devices.camera._temp = -60.0

    app = QApplication(sys.argv)
    win = MainWindow(system)
    win.worker.frame_ready.connect(lambda *_: results.__setitem__("frames", results["frames"] + 1))
    win.worker.spectrum_ready.connect(lambda *_: results.__setitem__("spectra", results["spectra"] + 1))
    win.worker.progress.connect(lambda *_: results.__setitem__("progress", results["progress"] + 1))
    win.worker.error.connect(lambda m: results["errors"].append(m))
    win.show()

    # Drive a sequence on the GUI timeline.
    QTimer.singleShot(200, win.acq_panel.single_requested.emit)
    QTimer.singleShot(700, lambda: win.acq_panel.scan_requested.emit(380.0, 520.0))
    QTimer.singleShot(2500, win._on_estop)
    QTimer.singleShot(3000, app.quit)

    app.exec()
    win.close()
    system.close_all()

    ok = (results["frames"] > 0 and results["spectra"] > 0
          and results["progress"] > 0 and not results["errors"]
          and system.safety.is_estopped and not system.shutter.is_open
          and not system.laser.is_enabled)
    print("SMOKE RESULTS:", results,
          "estopped=", system.safety.is_estopped,
          "shutter_open=", system.shutter.is_open,
          "laser_on=", system.laser.is_enabled)
    print("SMOKE", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
