# Hardware & Configuration Checklist

Open items to confirm before real operation, grouped by subsystem. Each item
notes **why it matters**, the **current placeholder** baked into the code, and
**where to set it**. Check items off as they're confirmed.

Legend: ⚠️ = safety-critical · 🔧 = needed for correct operation · 📋 = nice to have

---

## 1. Laser — NKT Origami XP

Control path: NKTPDLL Interbus SDK (`C:\Users\Public\Documents\NKT Photonics\SDK`),
wrapper `NKTP_DLL.py`. Driver: `spectrometer/drivers/laser_nkt.py`.

**CONFIRMED:** module **type `0x95` "Origami XPS"** at **COM6** (FTDI), address 15.
The laser speaks one of two mutually-exclusive interfaces on its port, selected
by Interbus reg `0x39` (0=NKTPBus, 1=CLI):

* **CLI (38400 ASCII) — PRIMARY.** Driver `OrigamiCLI` (`laser_origami_cli.py`).
  Unambiguous and DLL-free; resolves the earlier guesses. `ly_oxp2_standby/enabled`
  (emission), `ly_oxp2_output_enable/disable` (AOM fast gate, used in E-stop),
  `e_power=<0-4000>` (AOM/relative power → GUI %), `ly_oxp2_power=<W>` (pump power),
  `e_freq` + **`e_freq_available?`** (rep rate + queryable allowed list), `e_div`
  (pulse picker), `e_mlp?` (measured power).
* **Interbus (NKTPDLL) — retained.** Driver `OrigamiXPS` (`laser_nkt.py`), reg map
  from `95.txt`: `0x30` FSM (1=OFF confirmed), `0x34` shutter/AOM, `0x35` rep index
  (0=50 kHz), `0x36` U32 pulse picker, `0x05` relative power, `0x66` status.

`build_devices(laser_interface="cli"|"interbus")` selects; `origami_mode.ensure_mode`
switches the laser into the matching mode at startup.

| ✓ | Item | Why | Status |
|---|------|-----|--------|
| ☑ | ⚠️ **Module / port / interface** | Selects driver | `0x95` @ COM6; CLI primary |
| ☑ | ⚠️ **Emission OFF (E-stop)** | Kill beam | CLI: AOM disable + standby · Interbus: `0x34`=0 + FSM=1 (confirmed) |
| ☑ | ⚠️ **Emission ON** | Start emission | CLI `ly_oxp2_enabled` (unambiguous; no FSM guess) |
| ☑ | 🔧 **Rep-rate set + allowed list** | Discrete rates | CLI `e_freq` / `e_freq_available?` (queried at runtime) |
| ☑ | 📋 **Pulse picker** | 1/1..1/1,000,000 | CLI `e_div` / Interbus `0x36` |
| ☐ | 🔧 **AOM power (`e_power`) → actual output** | Calibrate the 0-4000 knob vs a power meter (firmware nJ vs mW; rep-rate-dependent max) | use `tests/origami_power_test.py` |
| ☐ | 🔧 **Max pump power (W)** | Bound `ly_oxp2_power` | `OrigamiCLI(max_pump_power_w=5.0)` — confirm |
| ☐ | 📋 **Interbus-only unknowns** | Only if using Interbus: FSM RUN state, rep-index table, `0x05` scaling | `OrigamiXPS` constants |

**Controls (`OrigamiCLI`):** `enable`/`disable` (E-stop = AOM off + standby),
`set/read_power_percent` (AOM), `set/read_pump_power_watts`,
`read_average_power_watts`, `set/read_pulse_picker_ratio`,
`set/read_repetition_rate_hz` (+ `allowed_rep_rates_hz` queried live).

**Remaining: calibrate the AOM power knob** with `tests/origami_power_test.py`
against a meter (which register/units actually drive output), and confirm the
max pump power. Then bench-verify enable/disable with the beam dumped.

---

## 2. Vacuum gauge (read-only)

Hardware: **Edwards TIC** controller + **wide-range gauge** (sensor), with an
**nXDS15i** backing pump and an **EXT (EXT406PM) turbo** pump. Per the locked
decision the software is READ-ONLY (reads the wide-range gauge to gate cooling;
never commands the pumps). Driver: `EdwardsTIC` (`vacuum_edwards.py`), wired into
the real factory path; `DummyVacuum` for offline. `VacuumController` is now
fail-safe (a gauge read error => `vacuum_ok=False`, so cooling is blocked).

TIC protocol: 9600 8N1, CR-terminated, object-ID commands (`?V913/914/915` =
gauge 1/2/3). Confirm the real format/slot/units with `tests/discover_edwards.py`.

| ✓ | Item | Why | Current value | Where to set |
|---|------|-----|---------------|--------------|
| ☐ | ⚠️ **Which gauge slot is the wide-range gauge** | Read the right sensor | `gauge=1` (object 913) | `build_devices(vacuum_gauge=...)` |
| ☐ | ⚠️ **Gauge units** (mbar/Torr/Pa) | Threshold + display must match | `"mbar"` | `build_devices(vacuum_units=...)` |
| ☐ | ⚠️ **Safe pressure threshold for cooling** | Camera mustn't cool above this | `1.0e-4` (arbitrary) | `build_system(cooling_threshold=...)` |
| ☐ | 🔧 **TIC COM port** | Serial connection | `COM7` (guess) | `build_devices(vacuum_port=...)` |
| ☐ | 🔧 **Value reply format** (`<p>;<unit>;<state>`?) | Correct parse | assumed `;`-separated, field0=pressure | `EdwardsTIC.parse_value_reply` |
| ☐ | 📋 **Pump object IDs** (turbo/backing) | Optional status display | turbo=904, backing=910 (guess) | `EdwardsTIC(turbo_object=, backing_object=)` |
| ☐ | 📋 **Loss-of-vacuum response** | Warn-only alarm | `SafetyManager.check_vacuum_while_cold` | — |

**Action:** run `python tests/discover_edwards.py [COM]` → identify the
wide-range gauge slot (setup/type reply), the value format, and the unit; set
`vacuum_gauge`/`vacuum_units`/`vacuum_port` accordingly.

---

## 3. Camera — Andor Newton DO920P (CONFIRMED from datasheet)

**Andor Newton CCD, model DO920P-BEN-995** (s/n CCD-26178); sensor **e2v CCD30-11**
(s/n 15102-01-23), **1024 × 256 px, 26 µm square pixels, 16-bit**. Full-well
~457,768 e⁻/px; read noise ~5-30 e⁻ (A/D rate 3/1/0.05 MHz × preamp ×1/×2/×4).
SDK2 (Driver Pack 2), tested on hw AG20.24 / SDK 2.104.33000.0. Driver:
`AndorCamera` (`andor_camera.py`); specs in `NEWTON_*` constants.

| ✓ | Item | Why | Value | Where |
|---|------|-----|-------|-------|
| ☑ | ⚠️ **Cooling setpoint + range** | Target temp | rated **-100..-20 °C**, typical **-80** | `camera.py` `MIN/MAX/DEFAULT_SETPOINT_C`; GUI spinbox |
| ☐ | ⚠️ **Fan policy while cold** | Air vs water cooling | default **fan 'full'** (air); set 'off' only if water-cooled — **CONFIRM** | `CameraController.cooling_fan_mode` |
| ☐ | ⚠️ **Vacuum level for turbo-cooling** | Safe-to-cool threshold (you're checking the doc) | `1e-4` placeholder | `build_system(cooling_threshold=)` |
| ☑ | ⚠️ **Warm-up target before cooler off** | Avoid thermal shock | `10 °C` | `CameraController.warm_target_c` |
| ☑ | 🔧 **Detector size / pixels** | Spectrum length + calibration | **1024 × 256**, 26 µm | `NEWTON_*`; calibration `n_pixels=1024` |
| ☑ | 🔧 **Model + SDK** | pylablib backend | Newton = **SDK2** (`AndorSDK2Camera`), `C:/Program Files/Andor Driver Pack 2` | `AndorCamera.sdk2_path` |
| ☑ | 📋 **Saturation level** | Guard threshold | `65000` (16-bit ADC; full-well 457,768 e⁻) | `SATURATION_LEVEL` |
| ☐ | 🔧 **Internal shutter / trigger mode** | Camera shutter vs external; sync | internal trigger assumed | `CameraController.configure` |
| ☐ | 📋 **A/D rate + preamp gain** | Sensitivity/noise | 3/1/0.05 MHz × ×1/×2/×4 (not exposed yet) | future `configure` |

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
