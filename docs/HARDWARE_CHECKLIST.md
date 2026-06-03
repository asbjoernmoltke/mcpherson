# Hardware & Configuration Checklist

Open items to confirm before real operation, grouped by subsystem. Each item
notes **why it matters**, the **current placeholder** baked into the code, and
**where to set it**. Check items off as they're confirmed.

Legend: ⚠️ = safety-critical · 🔧 = needed for correct operation · 📋 = nice to have

---

## 1. Laser — NKT Origami XP

Control path: NKTPDLL Interbus SDK (`C:\Users\Public\Documents\NKT Photonics\SDK`),
wrapper `NKTP_DLL.py`. Driver: `spectrometer/drivers/laser_nkt.py`.

Identified as the NKT **"Aeropulse mainboard" (module type `0x9D`)** — confirmed
register map from the SDK `Register Files/9D.txt`. The driver now consolidates
**all** controls into one connection (one `openPorts`), since the Interbus
won't allow a second process to open the same port.

Register map in use (preset `AEROPULSE_MAINBOARD` in `laser_nkt.py`):
`0x30` emission (0=off/1=seed/2=preamp/3=booster), `0x34` pulse-picker ratio,
`0x37` output level (0.1 %), `0x32` interlock, `0x66` status, `0x67` error.

| ✓ | Item | Why | Current value | Where to set |
|---|------|-----|---------------|--------------|
| ☐ | ⚠️ **Confirm module is type `0x9D`** when connected | Selects the whole register map | assumed `0x9D` (auto-detected on open) | `NKTLaser(regmap=...)` presets |
| ☐ | ⚠️ **Emission OFF = `0`** (verified-safe) | E-stop must kill the beam | `0x00` (consistent across NKT products) | `NKTRegisterMap.emission_off` |
| ☐ | ⚠️ **Emission ON stage** (booster=3?) | `enable()` must start full emission | `0x03` (booster, from `9D.txt`) | `NKTRegisterMap.emission_on` |
| ☐ | ⚠️ **Module address** on the Interbus | All reads/writes target this | `15` fallback; **auto-detected by type on open** | auto / `regmap.address` |
| ☐ | 🔧 **Amplifier rep-rate register** | Discrete rep rate (50-1000 kHz, default 50) is a *separate* control from the pulse picker; register not yet identified | `rep_rate_register=None` → GUI greys the control; `set_repetition_rate_hz` raises until set | `NKTRegisterMap.rep_rate_register` |
| ☐ | 🔧 **Laser COM port** | Which port the Origami enumerates as | auto-discover (`None`); NKT examples used `COM6` | `build_devices(laser_port=...)` |
| ☐ | 🔧 **Confirm Interbus vs PubOrigamiLib** | Does the generic scan see the Origami, or must we use `PubOrigamiLib.dll`? | assumes generic Interbus | run `tests/discover_nkt.py` with laser powered |
| ☐ | 📋 **Power register `0x37`** scaling (0.1 %/LSB) | Power set/read | `0x37`, 0.1 %/LSB | `NKTRegisterMap.power_register` |
| ☐ | 📋 **Pulse-picker range** | GUI allows 1/1 .. 1/1,000,000 (reg `0x34`) | 1 .. 1,000,000 | `ShutterLaserPanel` spinbox |
| ☐ | 📋 **Rep-rate values** | Discrete: 50,100,200..1000 kHz, default 50 | `STANDARD_REP_RATES_HZ` in `drivers/base.py` | confirm vs Origami |
| ☐ | 📋 **Sync/analog channel** | Currently unused; do we ever read it? | not read | future `read_sync()` hook |

**Controls now in the driver** (`NKTLaser`): `enable`/`disable` (E-stop),
`set_emission_stage`, `set_power_percent`/`read_power_percent`,
`set_pulse_picker_ratio`/`read_pulse_picker_ratio`,
`set_repetition_rate_hz`/`read_repetition_rate_hz` (needs base rate),
`read_status_bits`, `reset_interlock`.

**Action when laser is powered + connected:** run `python tests/discover_nkt.py`
→ confirm it reports module type `0x9D` and its address; then bench-verify
`enable`/`disable` toggle emission **with no experiment running** before
trusting the E-stop.

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
