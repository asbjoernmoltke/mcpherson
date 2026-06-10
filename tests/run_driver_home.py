"""Run the SHIPPED driver's hardened home() on real hardware -- COMMANDS MOTION.

Exercises ``MP_789A_4.home()`` (integer-status rewrite) end to end, including
the controller's high-accuracy Find-Home (``F1000,0``), which had never run on
hardware. Bounded by the limit switches + per-step timeouts inside home().

The driver's watchdog thread is now a joinable daemon, so this exits cleanly.

Run:  python tests/run_driver_home.py [COMport]    (default COM5)
"""
from __future__ import annotations

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.mcpherson import MP_789A_4  # noqa: E402
from spectrometer.utilities import log  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"


def main() -> int:
    log.register(level=logging.INFO, to_file=False)   # show driver progress
    print("=== Driver home() on %s -- COMMANDS MOTION, watch the grating ===" % PORT)

    drv = MP_789A_4(PORT)
    try:
        drv.open()      # connection is deferred to open() (not the constructor)
        print("Connected. Pre-home status ] = %d, position = %d."
              % (drv._limit_status(), drv.get_position()))
        t0 = time.monotonic()
        ok = drv.home()
        dt = time.monotonic() - t0
        print("\nhome() returned %s in %.1fs; position reset to %d."
              % (ok, dt, drv.get_position()))
        # NOTE: don't check the wide-flag bit here. The fine-find (F1000,0 under
        # A24) lands on the NARROW high-accuracy edge -- the home light goes off
        # and the wide A8 flag reads 0. The controller's F stops itself at home;
        # home() waits for that stop. Confirm on the bench instead:
        print("CONFIRM at the controller: mechanical counter ~2793 and the "
              "home light is OFF (light is on only while searching).")
        return 0 if ok else 1
    except Exception as exc:
        print("\nhome() raised: %s" % exc)
        drv.stop()
        return 1
    finally:
        drv.close()


if __name__ == "__main__":
    raise SystemExit(main())
