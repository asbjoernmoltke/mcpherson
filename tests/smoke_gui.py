"""Headless GUI smoke test (run with QT_QPA_PLATFORM=offscreen).

Builds the real MainWindow on dummy devices, drives a cooldown -> single ->
scan -> e-stop sequence through the actual Qt signal/worker plumbing, and
checks that frames/spectra/progress signals arrive. Also regression-tests the
AcquisitionWorker/AuxWorker thread split: a laser command and the aux status
poll must both keep working *while* a slowed-down grating home() is still
blocking the Acquisition thread -- before the split, both would have queued
behind it on the single shared worker thread. Not a pytest (needs a Qt event
loop); invoked directly by the test runner command.
"""
from __future__ import annotations

import os
import sys
import time

# Allow running directly by putting the repo root on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from spectrometer.core.system import build_system
from spectrometer.gui.main_window import MainWindow

results = {"frames": 0, "spectra": 0, "progress": 0, "errors": [],
           "aux_ticks_before_home": None, "aux_ticks_during_home": None,
           "laser_overlap_energy": None}


def main() -> int:
    # Acquisition does not require cooling, so we drive single/scan with the
    # camera at ambient -- exercising the uncooled-grab path.
    system = build_system(dummy=True, cooling_threshold=1.0e-4)
    system.open_all()

    # Slow the dummy grating's home() down to a ~1.5s block, so there's a
    # comfortable window to prove the laser/vacuum (Aux) thread keeps working
    # while the Acquisition thread is stuck inside it.
    orig_home = system.devices.grating.home

    def slow_home():
        time.sleep(1.5)
        return orig_home()
    system.devices.grating.home = slow_home

    app = QApplication(sys.argv)
    win = MainWindow(system)
    # Stub the close-time shutdown-disposition prompt: it's a real modal
    # QMessageBox in production, which would hang this headless test waiting
    # for a click that never comes.
    win._ask_shutdown_disposition = lambda: "safe"
    win.worker.frame_ready.connect(lambda *_: results.__setitem__("frames", results["frames"] + 1))
    win.worker.spectrum_ready.connect(lambda *_: results.__setitem__("spectra", results["spectra"] + 1))
    win.worker.progress.connect(lambda *_: results.__setitem__("progress", results["progress"] + 1))
    win.worker.error.connect(lambda m: results["errors"].append(m))
    win.aux_worker.error.connect(lambda m: results["errors"].append(m))
    aux_tick_count = {"n": 0}
    win.aux_worker.status_updated.connect(lambda *_: aux_tick_count.__setitem__("n", aux_tick_count["n"] + 1))
    win.show()

    # Drive a sequence on the GUI timeline.
    QTimer.singleShot(200, win.acq_panel.single_requested.emit)
    # Scans need a homed grating (#5) -- home before scanning. Patched
    # slow_home() makes this block the Acquisition thread for ~1.5s.
    QTimer.singleShot(700, win.grating_panel.home_requested.emit)

    # --- overlap check: fire a laser command *while* home() is still
    # blocking (700ms start + 1.5s duration = finishes ~2200ms) ---
    QTimer.singleShot(690, lambda: aux_tick_count.__setitem__(
        "before_home", aux_tick_count["n"]))
    QTimer.singleShot(900, lambda: win.laser_panel.energy_changed.emit(33.0))
    QTimer.singleShot(1000, lambda: results.__setitem__(
        "laser_overlap_energy", system.devices.laser.read_pulse_energy_uj()))
    QTimer.singleShot(2150, lambda: results.__setitem__(
        "aux_ticks_before_home", aux_tick_count.get("before_home", 0)))
    QTimer.singleShot(2150, lambda: results.__setitem__(
        "aux_ticks_during_home", aux_tick_count["n"]))

    # Scan now runs after the (slowed) home has finished (~2200ms).
    QTimer.singleShot(2400, lambda: win.acq_panel.scan_requested.emit(380.0, 520.0))
    # Exercise the new laser controls (energy / pulse-picker / rep-rate).
    QTimer.singleShot(3200, lambda: win.laser_panel.energy_changed.emit(12.0))
    QTimer.singleShot(3400, lambda: win.laser_panel.pulse_picker_changed.emit(8))
    QTimer.singleShot(3600, lambda: win.laser_panel.rep_rate_changed.emit(1.0e6))
    QTimer.singleShot(4200, win._on_estop)
    QTimer.singleShot(4700, app.quit)

    app.exec()
    win.close()

    # Rep rate and pulse picker are independent controls. After energy=12 µJ,
    # pulse-picker=1/8, rep-rate=1 MHz (=1000 kHz, an allowed discrete rate):
    laser = system.devices.laser
    laser_ok = (abs(laser.read_pulse_energy_uj() - 12.0) < 1e-6
                and laser.read_pulse_picker_ratio() == 8
                and laser.read_repetition_rate_hz() == 1.0e6)
    system.close_all()

    # The laser energy set at t=900 (while home() was still blocking) must
    # have taken effect by t=1000 -- i.e. well before home() finishes at
    # ~2200ms -- proving it wasn't queued behind the Acquisition thread.
    overlap_ok = (results["laser_overlap_energy"] is not None
                  and abs(results["laser_overlap_energy"] - 33.0) < 1e-6)
    # The Aux status poll (laser/vacuum) must keep ticking while the
    # Acquisition thread is blocked inside home().
    ticks_during_home = ((results["aux_ticks_during_home"] or 0)
                         - (results["aux_ticks_before_home"] or 0))
    aux_polling_ok = ticks_during_home >= 2

    ok = (results["frames"] > 0 and results["spectra"] > 0
          and results["progress"] > 0 and not results["errors"]
          and laser_ok and overlap_ok and aux_polling_ok
          and system.safety.is_estopped and not system.shutter.is_open
          and not system.laser.is_enabled)
    print("SMOKE RESULTS:", results,
          "overlap_ok=", overlap_ok,
          "ticks_during_home=", ticks_during_home,
          "estopped=", system.safety.is_estopped,
          "shutter_open=", system.shutter.is_open,
          "laser_on=", system.laser.is_enabled)
    print("SMOKE", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
