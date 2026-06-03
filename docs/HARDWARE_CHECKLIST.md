# Hardware & Configuration Checklist

Open items to confirm before real operation, grouped by subsystem. Each item
notes **why it matters**, the **current placeholder** baked into the code, and
**where to set it**. Check items off as they're confirmed.

Legend: ⚠️ = safety-critical · 🔧 = needed for correct operation · 📋 = nice to have

---

## 1. Laser — NKT Origami XP

Control path: NKTPDLL Interbus SDK (`C:\Users\Public\Documents\NKT Photonics\SDK`),
wrapper `NKTP_DLL.py`. Driver: `spectrometer/drivers/laser_nkt.py`.

**CONFIRMED:** module **type `0x95` "Origami XPS"** at **COM6** (FTDI), address
15 (`tests/discover_nkt.py`). Register map verified live (`tests/origami_status.py`)
against SDK `Register Files/95.txt`. Driver: `OrigamiXPS` in `laser_nkt.py`
(one connection; Interbus forbids a 2nd opener of the port).

Register map (Origami XPS): `0x30` FSM target state [1,3,5,6] (emission is a
state machine; **state 1 = OFF confirmed**), `0x34` internal shutter [0,1],
`0x35` rep-rate index [0-12] (**index 0 = 50 kHz confirmed**), `0x36`
frequency-division pulse picker [1-1,000,000] (U32), `0x05` relative power
[0-4000], `0x02/0x03` actual PRR (read), `0x66` status (bit0=Emission On),
`0x32` interlock, `0x67` error.

| ✓ | Item | Why | Current value | Where to set |
|---|------|-----|---------------|--------------|
| ☑ | ⚠️ **Module type / port / address** | Selects register map | `0x95` @ COM6 addr 15 (auto-detected) | confirmed |
| ☑ | ⚠️ **Emission OFF** | E-stop kills the beam | shutter `0x34`=0 **and** FSM `0x30`=1 (both confirmed) | `OrigamiXPS.disable()` |
| ☐ | ⚠️ **Emission RUN FSM state** | `enable()` must reach full emission | `FSM_RUN=6` (valid [1,3,5,6]) — **CONFIRM vs 3/5** | `OrigamiXPS.FSM_RUN` |
| ☐ | 🔧 **Power full-scale** (`0x05`=4000 ⇒ 100 %?) | Correct power % scaling | `POWER_FULL_SCALE=4000` — confirm | `OrigamiXPS.POWER_FULL_SCALE` |
| ☐ | 🔧 **Rep-rate index→kHz table** | Map indices 1-10 to 100-1000 kHz (index 0=50 confirmed) | assumed 1=100…10=1000 | `OrigamiXPS.REP_RATE_INDEX_HZ` |
| ☑ | 📋 **Pulse picker** | Frequency-division factor, 1/1..1/1,000,000 | reg `0x36` (U32) | confirmed |
| ☐ | 📋 **Sync/analog channel** | Currently unused | not read | future `read_sync()` hook |

**Controls in `OrigamiXPS`:** `enable` (FSM→RUN + open shutter) / `disable`
(close shutter + FSM→OFF, the E-stop), `set/read_power_percent`,
`set/read_pulse_picker_ratio` (U32), discrete `set/read_repetition_rate_hz`
(via index), `read_status_bits`, `reset_interlock`, `emission_stage`.

**To confirm the 3 remaining unknowns:** in NKT CONTROL, note which target
state runs emission (→ `FSM_RUN`); set power to a known % and read `0x05`
(→ scaling); step the rep rate and re-run `tests/origami_status.py` to read
`0x03` per index (→ index table). Then bench-verify `enable`/`disable` with the
beam safely dumped before trusting the E-stop.

---

## 2. Vacuum gauge (read-only)

Driver: `spectrometer/drivers/vacuum.py` (currently `DummyVacuum`).
Vacuum is controlled manually on isolated hardware — software only reads it.

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | ⚠️ **Safe pressure threshold for cooling** | Camera must not cool above this (interlock) | `1.0e-4` (arbitrary) | `VacuumController` `cooling_threshold` / `build_system` |
| ☐ | ⚠️ **Gauge units** (mbar / Torr / Pa) | Threshold + display must match the gauge | `"mbar"` | `DummyVacuum` / real driver `units` |
| ☐ | 🔧 **Gauge make/model** | Determines the read interface | none (dummy) | new real driver |
| ☐ | 🔧 **Read interface** (serial / analog / USB / display-only) | How software reads pressure | dummy returns a fixed value | new real `VacuumDriver` |
| ☐ | 🔧 **Output format / scaling** | Convert raw reading → pressure | n/a | new real driver |
| ☐ | 📋 **Loss-of-vacuum response** | We alarm (warn-only); confirm that's enough | alarm in `SafetyManager.check_vacuum_while_cold` | — |

---

## 3. Camera — Andor

Driver: `spectrometer/drivers/andor_camera.py` (real `AndorCamera` via pylablib).

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | ⚠️ **Operating cooling setpoint** (°C) | Target sensor temperature for acquisition | `-60` (GUI default) | GUI setpoint / `CameraController.cooldown` |
| ☐ | ⚠️ **Fan policy while cold** | Whether the fan may run during cold operation | not forced | `CameraController` / `set_fan_mode` |
| ☐ | ⚠️ **Warm-up target before cooler off** | Avoid thermal shock on shutdown | `10 °C` | `CameraController` `warm_target_c` |
| ☐ | 🔧 **Camera model + SDK DLL path** | Confirm pylablib finds the Andor SDK | `C:/Program Files/Andor Driver Pack 2` | `AndorCamera` `sdk2_path` |
| ☐ | 🔧 **Detector size** (pixels) | Spectrum length + calibration | assumes `2048` wide | read from camera at runtime |
| ☐ | 🔧 **Internal shutter mode** | Camera's own shutter vs external beam shutter | not set | `CameraController.configure` |
| ☐ | 🔧 **Trigger mode** (internal vs external) | Software-sync uses internal trigger | `"int"` assumed | `CameraController.configure` |
| ☐ | 📋 **Saturation level** | Saturation guard threshold | `65000` (16-bit) | `controllers/camera.py` `SATURATION_LEVEL` |
| ☐ | 📋 **Gain / amplifier settings** | Acquisition quality | not exposed yet | future |

---

## 4. Shutter (beam)

Driver: `spectrometer/drivers/shutter.py` (currently `DummyShutter`).
Software-synced with the camera (camera defines the exposure window).

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | 🔧 **Shutter make/model** | Determines the driver | none (dummy) | new real driver |
| ☐ | 🔧 **Interface** (TTL line / serial / USB) | How to open/close | dummy | new real `ShutterDriver` |
| ☐ | ⚠️ **Open/close travel time** | Sync settle delays around exposure | `0.05 s` | `DummyShutter.travel_time` / `SoftwareSync` settle |
| ☐ | ⚠️ **Independent E-stop channel** | Shutter-close must not queue behind a grating move | separate device (OK by design) | confirm wiring |

---

## 5. Grating — McPherson 789A-4

Driver: `spectrometer/drivers/mcpherson.py` (real, carried over and working).

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | 🔧 **Grating COM port** | Serial connection | `COM5` | `build_devices(grating_port=...)` |
| ☐ | 🔧 **Installed grating(s)** (g/mm) | Selects calibration + window width | `1200g/mm` default | `build_system(grating_name=...)` |
| ☐ | ⚠️ **Backlash steps** | Repeatable positioning | `0` | `GratingController` `backlash` |
| ☐ | 🔧 **Step ↔ position limits** | Avoid driving into end stops | driver limit switches + `1_000_000` soft cap | `mcpherson.py` / calibration |

---

## 6. Calibration (position ↔ wavelength)

Module: `spectrometer/core/calibration.py`. Current presets are **development
placeholders** (linear, ~200 nm window) and must be replaced with measured data.

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | 🔧 **Per-grating calibration data** | Accurate wavelength axis | synthetic linear presets | `default_calibration` / `LinearCalibration.from_file` |
| ☐ | 🔧 **Data source/format** | How calibration is produced/stored | JSON via `to_file/from_file` | `core/calibration.py` |
| ☐ | 🔧 **Center wavelength vs step** | Dispersion of the scan mechanism | `nm_per_step` presets | calibration file |
| ☐ | 🔧 **Dispersion across detector** | nm per pixel | `nm_per_pixel` presets | calibration file |
| ☐ | 📋 **Wavelength operating limits** | Guard scan range | `position_limits` | calibration |

---

## 7. System wiring / general

| ✓ | Item | Why | Current placeholder | Where to set |
|---|------|-----|---------------------|--------------|
| ☐ | 🔧 **COM-port map** (which port = which device) | Avoid grabbing the wrong port (e.g. COM3 = Intel AMT, not laser) | grating `COM5`, laser auto | `build_devices` / `build_system` |
| ☐ | 🔧 **Acquisition defaults** (exposure, frames, scan overlap, Δλ) | Sensible starting values | exposure `0.1 s`, frames `1`, overlap `0.15`, Δλ `0.05 nm` | GUI panels / `AcquisitionEngine` |
| ☐ | 📋 **Persisted settings** | Remember last-used values | not yet wired | `utilities/config.py` (future `core/state.py`) |

---

## Quick reference — discovered so far

- **COM3** = Intel AMT Serial-over-LAN (⚠️ *not* the laser).
- Laser **not yet connected/powered**; NKT bus scan (normal + legacy) found no modules.
- NKT plugin set present: `PubOrigamiLib.dll`, `PubAeroPulse{FS10,FS20,FS50,G3}Lib.dll`.
- aeroPulse FS50 emission: addr 15, reg `0x30`, ON=4, OFF=0; power reg `0x99` (%/0.1).
