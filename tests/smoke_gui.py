"""Headless GUI smoke test (run with QT_QPA_PLATFORM=offscreen).

Builds the real MainWindow on dummy devices, drives a cooldown -> single ->
scan -> e-stop sequence through the actual Qt signal/worker plumbing, and
checks that frames/spectra/progress signals arrive. Not a pytest (needs a Qt
event loop); invoked directly by the test runner command.
"""
from __future__ import annotations

import os
import sys

# Allow running directly by putting the repo root on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from spectrometer.core.system import build_system
from spectrometer.gui.main_window import MainWindow

results = {"frames": 0, "spectra": 0, "progress": 0, "errors": []}


def main() -> int:
    # Acquisition does not require cooling, so we drive single/scan with the
    # camera at ambient -- exercising the uncooled-grab path.
    system = build_system(dummy=True, cooling_threshold=1.0e-4)
    system.open_all()

    app = QApplication(sys.argv)
    win = MainWindow(system)
    win.worker.frame_ready.connect(lambda *_: results.__setitem__("frames", results["frames"] + 1))
    win.worker.spectrum_ready.connect(lambda *_: results.__setitem__("spectra", results["spectra"] + 1))
    win.worker.progress.connect(lambda *_: results.__setitem__("progress", results["progress"] + 1))
    win.worker.error.connect(lambda m: results["errors"].append(m))
    win.show()

    # Drive a sequence on the GUI timeline.
    QTimer.singleShot(200, win.acq_panel.single_requested.emit)
    # Scans need a homed grating (#5) -- home before scanning.
    QTimer.singleShot(700, win.grating_panel.home_requested.emit)
    QTimer.singleShot(1300, lambda: win.acq_panel.scan_requested.emit(380.0, 520.0))
    # Exercise the new laser controls (energy / pulse-picker / rep-rate).
    QTimer.singleShot(2100, lambda: win.laser_panel.energy_changed.emit(12.0))
    QTimer.singleShot(2300, lambda: win.laser_panel.pulse_picker_changed.emit(8))
    QTimer.singleShot(2500, lambda: win.laser_panel.rep_rate_changed.emit(1.0e6))
    QTimer.singleShot(3100, win._on_estop)
    QTimer.singleShot(3600, app.quit)

    app.exec()
    win.close()

    # Rep rate and pulse picker are independent controls. After energy=12 µJ,
    # pulse-picker=1/8, rep-rate=1 MHz (=1000 kHz, an allowed discrete rate):
    laser = system.devices.laser
    laser_ok = (abs(laser.read_pulse_energy_uj() - 12.0) < 1e-6
                and laser.read_pulse_picker_ratio() == 8
                and laser.read_repetition_rate_hz() == 1.0e6)
    system.close_all()

    ok = (results["frames"] > 0 and results["spectra"] > 0
          and results["progress"] > 0 and not results["errors"]
          and laser_ok
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
