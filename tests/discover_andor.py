"""Read-only Andor Newton discovery probe (Stage A) -- RUN AT THE CAMERA PC.

SAFE: opens the camera and READS its identity, detector geometry, temperature,
cooler/fan state, and the amplifier/exposure capabilities. It NEVER commands
cooling and NEVER changes the cooler or fan -- cooling is a separate, strictly
vacuum-gated step (Stage C). Exercises the real ``AndorCamera`` wrapper (the
code path the app uses) and also dips into the underlying pylablib handle for
SDK-specific detail.

Use this to confirm, before any cooling:
  * the detector size (expect 1024 x 256) and bit depth,
  * the current (ambient) temperature + cooler/fan state,
  * the A-D readout rates / pre-amp gains / EM-gain range, so we can check the
    driver's amp-mode enumeration against the real hardware, and
  * the fan policy (air-cooled 'full' vs water 'off').

Needs the Andor SDK2 (Driver Pack 2) + pylablib installed on this PC.

Run:  python tests/discover_andor.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectrometer.drivers.andor_camera import AndorCamera  # noqa: E402


def _show(label, fn):
    """Print 'label: value', or 'label: n/a (err)' if the query fails."""
    try:
        print("  %-22s %s" % (label + ":", fn()))
    except Exception as exc:
        print("  %-22s n/a (%s)" % (label + ":", exc))


def main() -> int:
    print("=== Andor Newton probe (READ-ONLY -- no cooling commanded) ===")
    cam = AndorCamera()
    try:
        cam.open()
    except Exception as exc:
        print("Could not open the camera: %s" % exc)
        print("Confirm the Andor SDK2 (Driver Pack 2) + pylablib are installed "
              "and no other program holds the camera.")
        return 1

    raw = cam._cam  # underlying pylablib AndorSDK2Camera, for richer SDK info
    try:
        print("\n-- Identity --")
        _show("status", cam.get_status)
        _show("device info", lambda: raw.get_device_info())
        _show("detector size (WxH)", cam.get_detector_size)

        print("\n-- Thermal (read-only) --")
        _show("temperature (C)", lambda: round(cam.get_temperature(), 1))
        _show("temp status", lambda: raw.get_temperature_status())
        _show("temp setpoint (C)", cam.get_temperature_setpoint)
        _show("cooler on", cam.is_cooler_on)
        _show("fan mode", cam.get_fan_mode)
        try:
            lo, hi = raw.get_temperature_range()
            print("  %-22s %s" % ("temp range (C):", (lo, hi)))
        except Exception as exc:
            print("  %-22s n/a (%s)" % ("temp range (C):", exc))

        print("\n-- Acquisition config (verify the driver's enumeration) --")
        _show("exposure (s)", cam.get_exposure)
        _show("trigger modes", cam.get_trigger_modes)
        _show("A-D readout rates", cam.get_readout_rates)
        _show("pre-amp gains", cam.get_preamp_gains)
        _show("EM gain range", cam.get_em_gain_range)
        print("  all amp modes (channel/oamp/hsspeed/preamp):")
        try:
            for m in raw.get_all_amp_modes():
                print("     ", m)
        except Exception as exc:
            print("      n/a (%s)" % exc)

        print("\nNo cooling was commanded; cooler/fan untouched. Next, ONLY with "
              "the chamber under vacuum, run the staged cooling lifecycle test.")
    finally:
        cam.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
