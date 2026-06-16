"""LIVE read-only monitor: watch pressure + pump states while roughing down.

Does NOT command anything -- just polls the gauge and pump states so we can see
the backing pump rough the chamber down toward the turbo-crossover / leak floor.

Run:  python tests/live_pump_monitor.py [seconds] [COMport]   (default 180 COM7)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.controllers.vacuum import VacuumController   # noqa: E402
from spectrometer.drivers.vacuum_edwards import EdwardsTIC     # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
PORT = sys.argv[2] if len(sys.argv) > 2 else "COM7"


def main() -> int:
    drv = EdwardsTIC(port=PORT, units="Pa")
    try:
        drv.open()
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        return 1
    vac = VacuumController(drv)
    try:
        print("=== pressure monitor (%.0fs) on %s ===" % (DURATION, PORT))
        t0 = time.time()
        while time.time() - t0 < DURATION:
            vac.poll()
            print("  %6.1fs  %.3e Pa | frost=%+.1fC min-safe=%+.1fC | "
                  "backing=%-12s turbo=%s"
                  % (time.time() - t0, vac.pressure, vac.frost_point_c,
                     vac.frost_point_c + 5.0, vac.backing_state,
                     vac.turbo_state))
            time.sleep(5)
    finally:
        drv.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
