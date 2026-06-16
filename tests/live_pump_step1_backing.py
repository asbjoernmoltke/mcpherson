"""LIVE step 1: software interlock check + start the BACKING pump, monitor.

Drives the real EdwardsTIC driver + VacuumController (the same code the GUI
buttons call) so we verify the control path on hardware, not just raw serial.

1. With both pumps stopped, calling turbo_on() must raise InterlockError
   (software refusal -- no hardware moves).
2. Start the backing pump (safe at atmosphere) and poll until it reports
   Running, watching the chamber pressure begin to fall.

Leaves the backing pump RUNNING (turbo started later, once roughed down).

Run:  python tests/live_pump_step1_backing.py [COMport]   (default COM7)
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


def main() -> int:
    drv = EdwardsTIC(port=PORT, units="Pa")
    try:
        drv.open()
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        print("If the GUI is connected to the vacuum, disconnect it first "
              "(it holds the COM port).")
        return 1
    vac = VacuumController(drv)
    try:
        print("=== LIVE pump step 1 on %s ===" % PORT)
        vac.poll()
        print("start: %.3e Pa | backing=%s turbo=%s"
              % (vac.pressure, vac.backing_state, vac.turbo_state))

        # 1) software refusal interlock (no hardware should move)
        print("\n[1] turbo_on() with backing stopped -> expect InterlockError")
        try:
            vac.turbo_on()
            print("    *** FAIL: turbo_on did NOT raise -- interlock broken!")
        except InterlockError as exc:
            print("    OK refused: %s" % exc)

        # 2) start the backing pump and watch it spin up
        print("\n[2] backing_on() -- starting backing pump")
        vac.backing_on()
        deadline = time.time() + 90
        while time.time() < deadline:
            vac.poll()
            running = vac.backing_running
            print("    %5.1fs  %.3e Pa | backing=%-14s turbo=%s"
                  % (90 - (deadline - time.time()), vac.pressure,
                     vac.backing_state, vac.turbo_state))
            if running:
                print("    -> backing pump REACHED RUNNING.")
                break
            time.sleep(3)
        else:
            print("    !! backing did not report Running within 90 s "
                  "(state=%s) -- check the pump." % vac.backing_state)

        print("\nBacking left RUNNING. Pressure should keep falling toward the "
              "leak-limited floor. Re-run the monitor or proceed to the turbo "
              "step once roughed down.")
    finally:
        drv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
