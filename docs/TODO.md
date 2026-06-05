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

- [ ] **5. Grating controller** — track a "homed" state, refuse absolute moves
  until homed, enforce calibrated position limits, validated go-to-wavelength.
- [ ] **6. Camera lifecycle in GUI** — cooldown → wait-until-stable with
  progress; sequenced warm-up/shutdown; expose gain / A-D rate / preamp /
  trigger / internal-shutter (only exposure is exposed now).

## Hardware bring-up (drivers exist; none verified on hardware)

- [ ] **7a.** Grating connection probe (`discover_mcpherson.py`).
- [ ] **7b.** Bench-test: camera cooling lifecycle, grating homing, laser power
  calibration + RUN state (`origami_power_test.py`), vacuum gauge read
  (`discover_edwards.py`); confirm COM ports + active grating.
- [ ] **7c.** Lamp wavelength calibration (see #2).

## Shutter (excluded for now)

- [ ] Real shutter driver once hardware is chosen (TTL/serial); confirm
  open/close travel time for sync settle.

## Optional / polish

- [ ] Dark-frame & background subtraction.
- [ ] On-chip / accumulate averaging UI.
- [ ] Packaging / launcher; log configuration.
