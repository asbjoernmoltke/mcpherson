# Hardware — Remaining Work

Only the items still open. The full verified reference (with rationale and the
values already confirmed) lives in [HARDWARE_CHECKLIST.md](HARDWARE_CHECKLIST.md).

Legend: ⚠️ safety-critical · 🔧 needed for correct operation · 📋 nice-to-have.
Ordered roughly by how ready each subsystem is to finish.

---

## Vacuum — TIC200 talking; mostly confirmed (2026-06-10)
Confirmed via `discover_edwards.py` / `discover_edwards_pumps.py` on **COM7**:
controller = **Edwards TIC200**; **gauge slot 1 / object 913** (914/915 = no
gauge); serial **unit = Pa** (1.0000e+05 Pa = 750 Torr = atm; the panel unit is
independent); value format `<p>;<unit>;<state>` (parser OK). Settings updated to
`vacuum_units="Pa"`.

- [ ] ⚠️ Set the **safe cooling threshold** — still TBD; now a `1e-2` **Pa** placeholder (= 1e-4 mbar) — `cooling_threshold`
- [◐] 📋 **Pump objects** found: turbo (nEXT85D) at **904** state / **905** speed / **906** power; backing (nXDS) at **910**. All read 0 now (pumps OFF at atmosphere). **Verify by watching obj 905 ramp 0→~100 % when you pump down**, then refine the GUI pump-status formatting (currently shows raw `0;0;0`).
- [ ] 📋 Decide the **loss-of-vacuum** alarm behaviour (warn-only) — `SafetyManager.check_vacuum_while_cold`

## Camera — offline-complete; staged bench bring-up pending
Needs `pylablib` + Andor SDK2 (Driver Pack 2) on the camera PC. A–B anytime the
camera is powered; **C–E require the chamber under vacuum.**

- [ ] **Stage A** — identify (SAFE, no cooling): `python tests/discover_andor.py`; verify the **A-D-rate / pre-amp / EM amp-mode mapping** against the real device
- [ ] **Stage B** — uncooled single + live frames (frame shape / bit-depth / saturation guard)
- [ ] ⚠️ **Stage C** — cooling lifecycle UNDER VACUUM: `cooldown` → progress → stable → cooled frame → `safe_shutdown` (controlled warm-up then cooler off)
- [ ] ⚠️ **Stage D** — interlock proof: `cooldown` is REFUSED above `cooling_threshold`
- [ ] ⚠️ **Stage E** — fan policy: air-cooled `'full'` vs water `'off'` — `CameraController.cooling_fan_mode`
- [ ] 🔧 Confirm **internal-shutter / trigger-mode** enum — `CameraController.configure`

## Grating — working; one item left
- [x] ⚠️ Trimmed **`F1000,0` fine-home** verified on hw 2026-06-10 — lands on counter **2793** (F self-stops at home; home light off). ~47 s from far, less when near.
- [x] ⚠️ **Backlash** measured 2026-06-10: same counter (2904.7) approaching a position from + and from − ⇒ backlash **≲ 900 steps ≈ ½ pixel**, negligible. **Kept `backlash = 0`**; set ~1000 only if a future lamp/camera check shows it matters.
- [ ] ⚠️ **Absolute λ offset** vs a lamp line — see Calibration (relative dispersion, steps/rev, direction already confirmed via the mechanical counter)

## Laser — controls coded; bench-verify + power calibration
- [ ] ⚠️ Bench-verify **enable/disable** (the E-stop path) with the beam dumped
- [ ] 🔧 **Calibrate AOM power** (`e_power` 0–4000 → actual output) against a power meter: `python tests/origami_power_test.py`
- [ ] 🔧 Confirm **max pump power** — `OrigamiCLI(max_pump_power_w=5.0)`
- [ ] 📋 Interbus-only unknowns (FSM RUN state, rep-index table, `0x05` scaling) — only if using the interbus path

## Shutter — no hardware chosen yet
- [ ] 🔧 Pick **make/model + interface** (TTL line / serial / USB) → write a real `ShutterDriver` (controllers depend only on the ABC, so nothing else changes)
- [ ] ⚠️ Measure **open/close travel time** for the sync settle (now `0.05 s`) — `DummyShutter.travel_time` / `SoftwareSync`
- [ ] ⚠️ Confirm the **independent E-stop channel** wiring (shutter-close must not queue behind a grating serial move)

## Calibration
- [ ] ⚠️ **Lamp line** (Hg/Ne/Ar) for the **absolute λ offset** (counter ~279.3 at fine home vs `wl0=279.70`); optionally fit + persist a measured calibration — `LinearCalibration.to_file`/`from_file`

## System wiring
- [ ] 🔧 Lock the **COM-port map** (grating COM5 ✓; confirm vacuum + laser ports). Optional: auto-detect by identify-handshake over `ports_finder.find_serial_ports()`
- [ ] 📋 Sanity-check the **acquisition defaults** (exposure 0.1 s, frames 1, scan overlap 0.15, Δλ 0.05 nm)

---

### Software follow-ups (no hardware needed)
- [ ] Verify the per-device **Connect/Disconnect** bars on real hardware (coded + offline-tested; the real-driver `open()` reconnect path is untested on hw).
- [ ] (Optional) Read-only pump status only becomes meaningful once the **TIC object IDs** above are confirmed.
- [ ] (Optional, separate task) Interlocked **pump control** (start/stop/standby) — deferred by design.
