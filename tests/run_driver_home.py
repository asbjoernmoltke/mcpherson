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
        print("Connected. Pre-home status ] = %d, position = %d."
              % (drv._limit_status(), drv.get_position()))
        t0 = time.monotonic()
        ok = drv.home()
        dt = time.monotonic() - t0
        print("\nhome() returned %s in %.1fs." % (ok, dt))
        # Confirm we're actually ON the flag: re-enable the home circuit (A0
        # left it disabled, which hides the home bit) and read the status.
        drv.s.xfer([b"A8"])
        on_flag = drv._limit_status()
        drv.s.xfer([b"A0"])
        print("Post-home: position = %d; home bit (with A8) = %d -> %s."
              % (drv.get_position(), on_flag,
                 "ON FLAG" if on_flag & drv.ST_HOME else "NOT on flag!"))
        return 0 if (ok and on_flag & drv.ST_HOME) else 1
    except Exception as exc:
        print("\nhome() raised: %s" % exc)
        drv.stop()
        return 1
    finally:
        drv.close()


if __name__ == "__main__":
    raise SystemExit(main())
