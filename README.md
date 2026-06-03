# McPherson Scanning Spectrometer

Integrated control software for a scanning spectrometer built from an **Andor
camera**, a **McPherson 789A-4** grating scan controller, a **beam shutter**, a
**pulsed laser**, and a read-only **vacuum gauge** — with a PyQt6 GUI, live data
preview, and hard safety interlocks.

## Architecture

A layered design (see `.claude/plans/dreamy-mapping-toast.md` for the full plan):

```
drivers/      Layer 1  thin hardware wrappers, each with a Dummy twin
controllers/  Layer 2  stateful, thread-confined device controllers
core/         Layer 3  safety, sync, acquisition, calibration, system wiring
gui/          Layer 5  PyQt6 + pyqtgraph (panels, live preview, E-stop)
utilities/             logging, mutex serial, port discovery, config
```

Key safety properties (all verified by tests):

- **Vacuum → cooling interlock**: the camera refuses to cool until the gauge
  reports sufficient vacuum; vacuum lost while cold raises a prominent alarm.
- **Controlled warm-up** before the cooler is switched off, on shutdown.
- **Emergency stop** closes the shutter *and* disables the laser, latches a
  global abort, and halts the grating/camera — wired directly so it stays
  responsive even while a scan is running.
- **Shutter ↔ camera** are software-synced (the camera defines the exposure
  window, the shutter brackets it); a `SyncController` seam allows hardware
  triggering to be added later.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`pylablib` is only needed for the real Andor camera; everything else (and the
full dummy/offline path) needs just numpy, scipy, pyserial, PyQt6, pyqtgraph.

## Running

```powershell
# Full GUI on simulated devices (no hardware):
python -m spectrometer.main --dummy

# Headless device self-test (no Qt, no hardware):
python -m spectrometer.main --dummy --selftest

# Real hardware (shutter/laser/vacuum still simulated until that
# hardware is selected — see plan open items):
python -m spectrometer.main
```

## Tests

```powershell
pytest -q                                   # unit + integration (dummy)
$env:QT_QPA_PLATFORM='offscreen'; python tests/smoke_gui.py   # headless GUI
```

## Status / open items

Scaffold complete and tested end-to-end against dummy devices. Before real
operation, confirm:

- Concrete **shutter**, **laser**, and **vacuum-gauge** hardware + interfaces
  (drivers are stubbed with dummies for these three).
- The **safe vacuum threshold** for cooling and the gauge's units.
- Cooling setpoint and whether the fan may run during cold operation.
- Per-grating **calibration** data (the `LinearCalibration` presets in
  `core/calibration.py` are development placeholders).
```
