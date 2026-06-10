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

- [ ] ⚠️ Set the **safe cooling threshold** — still TBD (now a `1e-2` **Pa** placeholder). Pump-down 2026-06-10 reached ~27 Pa with the turbo still spinning up; pick the threshold once we know the base pressure — `cooling_threshold`
- [x] 📋 **Pump status decoded + displayed** — turbo (nEXT85D) 904 state / 905 speed / 906 power, backing (nXDS) 910. State codes: turbo 0=stopped/5=starting/4=running, backing 0/4. GUI shows e.g. "Running, 78%".
- [ ] 📋 Decide the **loss-of-vacuum** alarm behaviour (warn-only) — `SafetyManager.check_vacuum_while_cold`

## Camera — Stages A+B done (2026-06-10); C–E need vacuum
- [x] **Stage A** — identify: DU920P_BEN s/n 26178, detector 1024×255, settable range **-50..+26 C** (fixed code: MIN=-50/DEFAULT=-45), amp-mode mapping CONFIRMED (3/1/0.05 MHz × 1/2/4×, conventional, no EM). Found+fixed: **camera comes up cooler-ON every open → `open()` now force-disables it when warm**.
- [x] **Stage B** — uncooled grab `(255,1024)` uint16, 1-D length 1024, live streaming, saturation guard — all OK; dark ~300 counts at 22 C/10 ms (`tests/acquire_andor.py`).
- [ ] ⚠️ **Cooling-unit switch (1 vs 2)** — the SDK's -50 C limit was read with the physical cooler switch on **position 1**; **position 2 is the deep/high-power cooling** (expected ~-100 C, likely water-assisted). When set to 2 + under vacuum: re-read the range and switch the code to **query `get_temperature_range()` dynamically** instead of the hardcoded -50.
- [ ] ⚠️ **Stage C** — cooling lifecycle UNDER VACUUM: `cooldown` → progress → stable → cooled frame → `safe_shutdown`. (Setpoint range hardcoded -50..-20 for switch pos 1; see above.)
- [ ] ⚠️ **Stage D** — interlock proof: `cooldown` REFUSED above `cooling_threshold`
- [ ] ⚠️ **Stage E** — fan policy: air-cooled `'full'` vs water `'off'` — `CameraController.cooling_fan_mode` (came up `'off'`)
- [ ] 🔧 Confirm **internal-shutter / trigger-mode** enum — `CameraController.configure`

## Grating — working; one item left
- [x] ⚠️ Trimmed **`F1000,0` fine-home** verified on hw 2026-06-10 — lands on counter **2793** (F self-stops at home; home light off). ~47 s from far, less when near.
- [x] ⚠️ **Backlash** measured 2026-06-10: same counter (2904.7) approaching a position from + and from − ⇒ backlash **≲ 900 steps ≈ ½ pixel**, negligible. **Kept `backlash = 0`**; set ~1000 only if a future lamp/camera check shows it matters.
- [ ] ⚠️ **Grating identity + true dispersion + absolute λ** — all need a lamp line (or the grating's physical label). The counter test only confirmed the drive (36000 steps/rev) + mechanism direction, NOT the grating; installed is **believed 599.45 g/mm**. NB: if 599.45, the mechanical counter reads ~½ true λ (it's geared to a 1200 reference), so don't trust the counter as the absolute reference for this grating.

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
