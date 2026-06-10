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

Hardware: **Edwards TIC200** controller + **wide-range gauge** (sensor, object
913), with an **nXDS** backing pump and a **nEXT85D** turbo pump. Per the locked
decision the software is READ-ONLY (reads the wide-range gauge to gate cooling;
never commands the pumps). Driver: `EdwardsTIC` (`vacuum_edwards.py`), wired into
the real factory path; `DummyVacuum` for offline. `VacuumController` is now
fail-safe (a gauge read error => `vacuum_ok=False`, so cooling is blocked).

TIC protocol: 9600 8N1, CR-terminated, object-ID commands (`?V913/914/915` =
gauge 1/2/3). Confirm the real format/slot/units with `tests/discover_edwards.py`.

| ✓ | Item | Why | Current value | Where to set |
|---|------|-----|---------------|--------------|
| ☑ | ⚠️ **Which gauge slot is the wide-range gauge** | Read the right sensor | **object 913 / slot 1 confirmed** (914/915 = no gauge) | `build_devices(vacuum_gauge=1)` |
| ☑ | ⚠️ **Gauge units** | Threshold + display must match | **serial = Pa confirmed** (1e5 Pa = 750 Torr; panel unit independent) | `vacuum_units="Pa"` |
| ☐ | ⚠️ **Safe pressure threshold for cooling** | Camera mustn't cool above this | **TBD** — `1e-2` Pa placeholder (= 1e-4 mbar) | `build_system(cooling_threshold=...)` |
| ☑ | 🔧 **TIC COM port** | Serial connection | **COM7 confirmed** (FTDI `0403:6015`); controller = TIC200 | `build_devices(vacuum_port=...)` |
| ☑ | 🔧 **Value reply format** | Correct parse | **`<p>;<unit>;<state>` confirmed**, field0=pressure | `EdwardsTIC.parse_value_reply` |
| ◐ | 📋 **Pump objects** (turbo nEXT85D / backing nXDS) | Read-only status display | turbo 904(state)/905(speed)/906(power), backing 910 — respond, OFF at atm; verify obj 905 ramps when pumping | `EdwardsTIC(turbo_object=, backing_object=)` |
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
| ☐ | 🔧 **Internal shutter / trigger mode** | Camera shutter vs external; sync | exposed in GUI; defaults assumed — confirm enum at Stage A | `CameraController.configure` |
| ◐ | 📋 **A/D rate + preamp gain** | Sensitivity/noise | exposed in the Camera panel; **verify the index<->mode mapping at Stage A** | `AndorCamera.set_amp_mode`; `discover_andor.py` |

**Bring-up plan (read-only first; cooling is vacuum-gated):**
- **Stage A — identify (SAFE, no cooling):** `python tests/discover_andor.py` —
  reads model/detector size/temperature/cooler+fan state and the amp-mode /
  readout-rate / pre-amp / EM-gain enumeration (to check the driver's mapping).
- **Stage B — uncooled acquisition:** single + live frames at ambient (cooling
  isn't required to acquire); check frame shape/bit-depth + saturation guard.
- **Stage C — cooling lifecycle (HIGH RISK; only under vacuum):** `cooldown()`
  → watch ramp + `cooldown_progress` → `wait_until_stable` → cooled frame →
  `safe_shutdown` (controlled warm-up to `warm_target_c` then cooler off).
- **Stage D — interlock proof:** confirm `cooldown()` is REFUSED when the gauge
  reads above `cooling_threshold`.
- **Stage E — fan policy:** confirm air-cooled `'full'` vs water `'off'`.
  Stages A-B anytime the camera is powered; C-E require the chamber at vacuum.

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

## 5. Grating — McPherson 234/302 + 789A-4 (CONFIRMED from spec)

**McPherson 234/302** monochromator (s/n 302438), **200 mm f.l., f/4.5**, driven
by the **789A-4** scan controller (`mcpherson.py`). Protocol = **ASCII decimal**
(commands like `+72000`, `M+23000`, `F1000,0`; the `]` limit query returns a
decimal bit-sum: 2=moving, 32=home blocked, 64/128=upper/lower limit). Drive:
18000 motor-steps/rev, **36000 controller-steps/rev** (half-stepped; confirmed
by the homing −108000="3 rev").

| ✓ | Item | Why | Value | Where |
|---|------|-----|-------|-------|
| ☑ | 🔧 **Monochromator + drive** | Calibration basis | 234/302, 200 mm f/4.5; 36000 steps/rev | `calibration.py` `MCPHERSON_234_302` |
| ☑ | 🔧 **Gratings + home λ** | Dispersion + reference | 2400 (279.70), 1200 (279.70), 599.45 (279.82) | `MCPHERSON_234_302` |
| ☑ | 🔧 **Grating COM port** | Serial connection | **COM5 confirmed** (FTDI `0403:6001`, fw v2.55) | `build_devices(grating_port=...)` |
| ☑ | 🔧 **Active grating** | Which one is installed now | **1200 g/mm confirmed** (measured 2.0 nm/rev) | `build_system(grating_name=...)` |
| ☑ | ⚠️ **steps/rev = 36000 vs 18000** | 2× factor on λ | **36000 confirmed**: +18000 steps = half a knob turn | `calibration.py` `STEPS_PER_MOTOR_REV=36000` |
| ☑ | ⚠️ **Scan direction sign** | Does +steps raise or lower λ | **+1 confirmed**: +steps raised the counter | `calibration.py` `DIRECTION=+1` |
| ☑ | ⚠️ **Backlash steps** | Repeatable positioning | **measured ≲900 steps ≈ ½ pixel (2026-06-10) → negligible; kept `0`** | `GratingController.backlash` |

**Bring-up 2026-06-08 (verified):** identify + read-only status (`tests/discover_mcpherson.py`); bounded jog ±20000 (`jog_mcpherson.py`); coarse home + off-and-back sweep (`home_mcpherson.py`, `verify_home_mcpherson.py`); **the shipped `MP_789A_4.home()` now lands on the flag in ~12 s and confirms ON FLAG** (`run_driver_home.py`). **`]` home bit (32) only shows after `A8`** — the read-only probe can falsely read "off home". Home is the `−` direction. `home()`/status handling rewritten to integer bit-parsing (substring checks misfired: '2' in '32', missed 66=upper+moving); watchdog thread now a joinable daemon.

**Calibration confirmed via the mechanical counter (no lamp needed):** +18000 steps = **half a knob turn ⇒ 36000 steps/rev**; counter +1.0 nm / 18000 steps ⇒ **nm/step 5.56e-5** (= 1200 g/mm spec), **+steps raises λ ⇒ DIRECTION=+1**. All match the code — no calibration changes.

**Still TODO (hw):** the controller's **`F1000,0` fine-edge find actually WORKS** (earlier "broken" was a too-short 60 s timeout: it needs ~94 s with a 72000 settle; refines home 2781→2793). Re-instate it in `home()` with a trimmed settle (`-10000`) + adequate timeout. Absolute λ offset still wants a lamp-line check (counter ~279.3 at fine home vs `wl0=279.70`).

---

## 6. Calibration (position ↔ wavelength) — DERIVED, lamp-verify pending

`core/calibration.py` now holds the **real 234/302** linear calibration per
grating (replacing the placeholders): `nm_per_step = nm_per_motor_rev / 36000`,
`nm_per_pixel = dispersion(nm/mm) × 0.026 mm` (Newton 26 µm), home λ at step 0.

| Grating | nm/step | nm/pixel | window (1024 px) | step range |
|---|---|---|---|---|
| 1200 | 5.556e-5 | 0.104 | 106.5 nm | −4.49M … +4.87M |
| 2400 | 2.778e-5 | 0.052 | 53.2 nm | −8.99M … −0.17M |
| 599.45 | 1.111e-4 | 0.208 | 213 nm | −2.25M … +7.38M |

| ✓ | Item | Why | Status |
|---|------|-----|--------|
| ☑ | 🔧 **Per-grating dispersion + nm/step** | Wavelength axis | spec + **counter-confirmed** (1200: 5.56e-5 nm/step) |
| ◐ | ⚠️ **Lamp verification** | steps/rev (36000) ☑ + direction (+1) ☑ via counter; **absolute λ offset** still open | measure Hg/Ne/Ar line, fit offset |
| ☐ | 📋 **Persisted measured calibration** | Use a fitted file over the nominal | `LinearCalibration.to_file/from_file` |

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
