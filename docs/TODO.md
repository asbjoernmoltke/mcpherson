# Implementation TODO / Roadmap

Status of remaining work beyond the device drivers (camera, grating, laser,
vacuum all have real drivers; **shutter** is still dummy-only). See
`HARDWARE_CHECKLIST.md` for per-device hardware parameters to confirm.

## Functional gaps (software)

- [ ] **1. Data saving / export** (IN PROGRESS) — save spectra + frames with a
  flexible metadata dict; CSV default for single, HDF5 for repeated; save
  dialog (path/name/format/operation mode/metadata). Metadata as a dict dumped
  to a header (single) or info file / HDF5 attrs (series) so new parameters
  never require reshaping the writer.
- [ ] **2. Calibration measurement routine** — step the grating, capture
  Hg/Ne/Ar lamp lines, fit `center_wavelength(steps)` + `nm/pixel`, save a
  measured `LinearCalibration`. Resolves the 36000-vs-18000 steps/rev (2×),
  the scan direction sign, and the absolute λ offset.
- [ ] **3. Settings / state persistence** — `core/state.py` (planned Layer 4):
  remember last exposure, grating, setpoint, scan range, ports, save folder.
  Use `utilities/config.py` (currently unused).
- [x] **4. Live-view mode** — continuous preview via the camera's
  `start_acquisition`/`read_newest_image`, wired to a "Live" toggle button.
  Opens the shutter while live, streams frame + reduced spectrum, stops on
  toggle/abort/E-stop.

## Controller / lifecycle hardening (code-only)

- [x] **5. Grating controller** — tracks a "homed" state (`is_homed`); refuses
  absolute moves (and wavelength moves / scans) until homed; validates targets
  against the calibration's position limits (`OutOfRangeError`) and the
  reachable wavelength range; `stop()` invalidates the homed reference. GUI
  shows a "Homed" lamp and disables Go-to-λ until homed.
- [x] **6. Camera lifecycle in GUI** — cooldown progress bar (poll-driven,
  non-blocking) + non-blocking warm-up state machine driven from the status
  poll (no GUI freeze); `begin_warmup`/`is_warm_enough`/`finish_shutdown`
  split with a blocking `safe_shutdown` kept for teardown. Config controls
  exposed: trigger, internal-shutter, A-D readout rate, pre-amp gain, EM gain
  (greyed when unsupported), populated from the camera's reported caps.
  *Bench-verify the real Andor amp-mode index mapping (`set_amp_mode`).*

## Hardware bring-up (drivers exist; none verified on hardware)

- [x] **7a.** Grating connection probe (`discover_mcpherson.py`) — **done**:
  COM5 confirmed (FTDI, fw v2.55), read-only identify + status.
- [ ] **7b.** Bench-test: camera cooling lifecycle, **grating homing (◐ shipped
  `home()` lands on the flag in ~12 s, verified 2026-06-08; the controller's
  `F1000,0` fine-edge find is broken/removed pending the 789A-4 manual)**,
  laser power calibration + RUN state (`origami_power_test.py`), vacuum gauge
  read (`discover_edwards.py`); confirm COM ports + active grating.
- [ ] **7c.** Lamp wavelength calibration (see #2).

## Shutter (excluded for now)

- [ ] Real shutter driver once hardware is chosen (TTL/serial); confirm
  open/close travel time for sync settle.

## Optional / polish

- [ ] Dark-frame & background subtraction.
- [ ] On-chip / accumulate averaging UI.
- [ ] Packaging / launcher; log configuration.
