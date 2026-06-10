"""Safe the Andor camera's cooling: fan FULL, then cooler OFF -- COMMANDS.

For when the camera comes up with the cooler enabled but no chamber vacuum (or
fan off). The TEC is the only active heat source, so disabling it returns the
camera to passive ambient -- that PREVENTS hot-side overheating. We turn the
fan to full first to dissipate any heat the hot side already accumulated, then
disable the cooler. No warm-up ramp is needed because the sensor is at ambient
(disabling cooling from ambient has no thermal-shock risk).

Run:  python tests/cooler_off_andor.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.andor_camera import AndorCamera  # noqa: E402


def state(cam) -> str:
    return ("temp=%.1f C, setpoint=%.1f C, cooler=%s, fan=%s"
            % (cam.get_temperature(), cam.get_temperature_setpoint(),
               cam.is_cooler_on(), cam.get_fan_mode()))


def main() -> int:
    print("=== Safe the Andor cooling (fan FULL, then cooler OFF) ===")
    cam = AndorCamera()
    try:
        cam.open()
    except Exception as exc:
        print("Could not open the camera: %s" % exc)
        return 1
    try:
        print("Before:", state(cam))

        # Refuse to act blind if the sensor is actually cold -- a controlled
        # warm-up (safe_shutdown) would be needed instead of a bare cooler-off.
        if cam.get_temperature() < 5.0:
            print("Sensor is COLD (<5 C). NOT doing a bare cooler-off -- use the "
                  "controlled warm-up (safe_shutdown) instead. Aborting.")
            return 1

        print("Fan -> full (dissipate hot-side heat)...")
        cam.set_fan_mode("full")
        time.sleep(1.0)
        print("Cooler -> off...")
        cam.set_cooler(False)
        time.sleep(1.0)

        print("After: ", state(cam))
        print("Cooler is off; the camera will sit at ambient. Safe for Stage B "
              "(uncooled frames).")
        return 0
    finally:
        cam.close()


if __name__ == "__main__":
    raise SystemExit(main())
