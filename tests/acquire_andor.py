"""Stage B: uncooled Andor acquisition test -- COMMANDS (acquisition only).

SAFE re: cooling -- never enables the cooler (open() force-disables it warm).
Acquisition does not require cooling; this verifies the frame path on the real
camera at ambient: a blocking grab (shape / dtype / stats / saturation), the
1-D reduction, and the live read_newest_image streaming path. A warm sensor has
high dark signal, so a long exposure may saturate -- that's expected and is
exactly what cooling later reduces; we use a short exposure here.

Run:  python tests/acquire_andor.py [exposure_s]   (default 0.01)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from spectrometer.core.acquisition import reduce_frames  # noqa: E402
from spectrometer.drivers.andor_camera import AndorCamera  # noqa: E402

EXPOSURE_S = float(sys.argv[1]) if len(sys.argv) > 1 else 0.01


def main() -> int:
    print("=== Andor Stage B: uncooled acquisition (no cooling) ===")
    cam = AndorCamera()
    try:
        cam.open()
    except Exception as exc:
        print("Could not open the camera: %s" % exc)
        return 1
    try:
        print("temp=%.1f C, cooler=%s (must be False)"
              % (cam.get_temperature(), cam.is_cooler_on()))
        cam.set_exposure(EXPOSURE_S)
        print("exposure=%.4f s, detector (WxH)=%s" % (cam.get_exposure(),
                                                      cam.get_detector_size()))

        print("\n-- blocking grab(1) --")
        frames = cam.grab(1)
        f = frames[0] if frames.ndim == 3 else frames
        print("  stack shape=%s dtype=%s" % (frames.shape, frames.dtype))
        print("  frame shape=%s  min=%d max=%d mean=%.1f"
              % (f.shape, int(f.min()), int(f.max()), float(f.mean())))
        print("  saturated (>=65000): %s%s"
              % (int(f.max()) >= 65000,
                 "  (expected at ambient -- cooling reduces dark)" if int(f.max()) >= 65000 else ""))
        spec = reduce_frames(frames)
        print("  1-D spectrum length=%d (expect 1024)" % spec.size)

        print("\n-- live read_newest_image x ~1s --")
        cam.start_acquisition()
        got, t = 0, time.time()
        while time.time() - t < 1.0:
            if cam.read_newest_image() is not None:
                got += 1
            time.sleep(0.03)
        cam.stop_acquisition()
        print("  live frames read: %d" % got)

        print("\nFrame path OK." if (f.shape[-1] == 1024 and spec.size == 1024 and got > 0)
              else "\nCheck the results above.")
        return 0
    finally:
        cam.close()


if __name__ == "__main__":
    raise SystemExit(main())
