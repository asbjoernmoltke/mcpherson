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
  measured `LinearCalibration`. ◐ steps/rev (**36000**), direction (**+1**),
  and 1200 g/mm dispersion (**5.56e-5 nm/step**) already confirmed via the
  mechanical counter (2026-06-08); only the **absolute λ offset** + `nm/pixel`
  still need a lamp line.
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
- [ ] **7b.** Bench-test: camera cooling lifecycle, **grating homing (◐ coarse
  home verified on hw 2026-06-08; `F1000,0` fine-edge find works (~94 s @ 72k
  settle) and is now re-instated in `home()` with a trimmed -10000 settle —
  this trimmed path is NOT yet re-verified on hw)**, laser power calibration +
  RUN state (`origami_power_test.py`), vacuum gauge read
  (`discover_edwards.py`); confirm COM ports + active grating.
- [ ] **7c.** Lamp wavelength calibration (see #2).

## Shutter (excluded for now)

- [ ] Real shutter driver once hardware is chosen (TTL/serial); confirm
  open/close travel time for sync settle.

## Connection management

- [x] **Per-device connect/disconnect** — each hardware panel has a
  `ConnectionBar` (status + Connect/Disconnect); offline-safe status poll;
  best-effort open at startup so the GUI launches with devices offline.
- [ ] **Defer real-driver connection to `open()`** — the connect/disconnect
  bars fully work with the dummies, but the REAL drivers (`MP_789A_4`,
  `EdwardsTIC`, `OrigamiCLI`) connect in their *constructor* and their
  `open()` is a no-op, so on hardware: (a) a missing port fails at build time
  (not start-offline), and (b) Connect won't re-open a closed port. Refactor
  the real drivers to connect/reconnect in `open()` for the bars to work on
  hardware. (Also enables real COM-port auto-detection / re-scan.)
- [ ] **COM-port auto-detection** — currently ports are fixed in `Settings`
  (grating COM5, vacuum COM7, laser COM6/NKT bus scan); add identify-by-
  handshake over `ports_finder.find_serial_ports()` to auto-assign devices.

## Optional / polish

- [ ] Dark-frame & background subtraction.
- [ ] On-chip / accumulate averaging UI.
- [ ] Packaging / launcher; log configuration.
