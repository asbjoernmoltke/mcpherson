"""Run the Andor fan to flush residual hot-side heat, then turn it off.

Use AFTER the cooler has been turned off (see cooler_off_andor.py): the fan
clears the heat the hot side accumulated while the TEC was stalled, then we
return the fan to 'off' (the camera's passive idle state). Aborts if the cooler
is somehow still on (don't turn the fan off while actively cooling).

Run:  python tests/fan_settle_off_andor.py [settle_seconds]   (default 60)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.andor_camera import AndorCamera  # noqa: E402

SETTLE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0


def state(cam) -> str:
    return ("temp=%.1f C, cooler=%s, fan=%s"
            % (cam.get_temperature(), cam.is_cooler_on(), cam.get_fan_mode()))


def main() -> int:
    cam = AndorCamera()
    try:
        cam.open()
    except Exception as exc:
        print("Could not open the camera: %s" % exc)
        return 1
    try:
        print("State:", state(cam))
        if cam.is_cooler_on():
            print("Cooler is still ON -- not turning the fan off. Run "
                  "cooler_off_andor.py first. Aborting.")
            return 1
        cam.set_fan_mode("full")
        print("Fan full; flushing residual hot-side heat for %.0fs..." % SETTLE_S)
        time.sleep(SETTLE_S)
        cam.set_fan_mode("off")
        time.sleep(0.5)
        print("Done:", state(cam))
        print("Camera idle at ambient, cooler off, fan off. Ready for Stage B.")
        return 0
    finally:
        cam.close()


if __name__ == "__main__":
    raise SystemExit(main())
