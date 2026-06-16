"""LIVE step 2: start the TURBO (backing already running), test interlocks, stop.

Assumes step 1 left the backing pump RUNNING and the chamber roughed down to a
safe turbo-crossover pressure. Exercises the real VacuumController path:

1. turbo_on() -- accepted now backing is Running; confirm it ACCELERATES.
2. backing_off() while the turbo spins -- must raise InterlockError (reverse
   interlock: turbo needs the backing pump to exhaust).
3. turbo_off() -- brake the turbo; poll until it reports Stopped.

Leaves the BACKING pump running (so the chamber keeps roughing). Stopping the
backing pump is a separate, deliberate step.

Run:  python tests/live_pump_step2_turbo.py [COMport]   (default COM7)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.core.exceptions import InterlockError       # noqa: E402
from spectrometer.controllers.vacuum import VacuumController   # noqa: E402
from spectrometer.drivers.vacuum_edwards import EdwardsTIC     # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
SPINUP_S = 45.0       # brief spin-up: enough to prove acceleration
BRAKE_TIMEOUT_S = 240.0


def main() -> int:
    drv = EdwardsTIC(port=PORT, units="Pa")
    try:
        drv.open()
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1
    vac = VacuumController(drv)
    try:
        print("=== LIVE pump step 2 (turbo) on %s ===" % PORT)
        vac.poll()
        print("start: %.3e Pa | backing=%s turbo=%s"
              % (vac.pressure, vac.backing_state, vac.turbo_state))
        if not vac.backing_running:
            print("!! backing pump is NOT running -- run step 1 first. Aborting.")
            return 1

        # 1) start the turbo and confirm acceleration
        print("\n[1] turbo_on() -- starting turbo")
        vac.turbo_on()
        t0 = time.time()
        while time.time() - t0 < SPINUP_S:
            vac.poll()
            print("    %4.1fs  %.3e Pa | turbo=%-16s backing=%s"
                  % (time.time() - t0, vac.pressure, vac.turbo_state,
                     vac.backing_state))
            time.sleep(3)
        print("    -> turbo accelerating (see speed %% climbing above).")

        # 2) reverse interlock: backing must NOT stop while turbo spins
        print("\n[2] backing_off() while turbo spins -> expect InterlockError")
        try:
            vac.backing_off()
            print("    *** FAIL: backing_off did NOT raise -- interlock broken!")
        except InterlockError as exc:
            print("    OK refused: %s" % exc)

        # 3) stop the turbo; poll until braked to Stopped
        print("\n[3] turbo_off() -- braking turbo to Stopped")
        vac.turbo_off()
        t0 = time.time()
        while time.time() - t0 < BRAKE_TIMEOUT_S:
            vac.poll()
            code = drv.turbo_state_code()
            print("    %5.1fs  %.3e Pa | turbo=%-16s"
                  % (time.time() - t0, vac.pressure, vac.turbo_state))
            if code == 0:
                print("    -> turbo STOPPED.")
                break
            time.sleep(5)
        else:
            print("    !! turbo not Stopped within %.0fs (still braking?)."
                  % BRAKE_TIMEOUT_S)

        print("\nBacking pump left RUNNING. Stopping backing is a separate step "
              "(backing_off() -- now allowed since the turbo is stopped).")
    finally:
        drv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
