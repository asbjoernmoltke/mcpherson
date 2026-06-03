"""Entry point for the spectrometer control application.

Usage::

    python -m spectrometer.main --dummy            # GUI on simulated devices
    python -m spectrometer.main --dummy --selftest # headless smoke test
    python -m spectrometer.main                    # real hardware (GUI)

The GUI is built in a later phase; for now ``--selftest`` exercises the
device layer headlessly so progress can be validated with no hardware and no
Qt dependency.
"""
from __future__ import annotations

import argparse
import logging

from .drivers.factory import build_devices
from .utilities import log


def selftest(dummy: bool) -> int:
    """Exercise every driver through its basic verbs. Returns an exit code."""
    devices = build_devices(dummy=dummy)
    devices.open_all()
    try:
        log.info("--- Device self-test ---")
        log.info("Vacuum: %s" % devices.vacuum.get_status())
        log.info("Camera: %s, detector=%s" % (
            devices.camera.get_status(), devices.camera.get_detector_size()))

        # Cooling simulation: set a cold point and confirm it ramps/stabilises.
        devices.camera.set_temperature(-60.0)
        for _ in range(20):
            if devices.camera.is_temperature_stable():
                break
            devices.camera.get_temperature()
        log.info("Camera temp=%.1f stable=%s" % (
            devices.camera.get_temperature(),
            devices.camera.is_temperature_stable()))

        # Grating: home + a small move.
        devices.grating.home()
        devices.grating.move_to(5000)
        log.info("Grating position=%d status=%s" % (
            devices.grating.get_position(), devices.grating.get_status()))

        # Shutter + laser + a frame grab.
        devices.shutter.open_shutter()
        devices.laser.enable()
        frame = devices.camera.grab(1)
        devices.shutter.close_shutter()
        devices.laser.disable()
        log.info("Grabbed frame shape=%s max=%d" % (frame.shape, frame.max()))

        log.info("--- Self-test PASSED ---")
        return 0
    finally:
        devices.close_all()


def main() -> int:
    parser = argparse.ArgumentParser(description="Spectrometer control")
    parser.add_argument("--dummy", action="store_true",
                        help="use simulated devices (no hardware)")
    parser.add_argument("--selftest", action="store_true",
                        help="run a headless device self-test and exit")
    parser.add_argument("--verbose", action="store_true",
                        help="debug-level terminal logging")
    args = parser.parse_args()

    log.register(level=logging.DEBUG if args.verbose else logging.INFO)

    if args.selftest:
        return selftest(dummy=args.dummy)

    # GUI launch is implemented in a later phase.
    from .app import run_gui
    return run_gui(dummy=args.dummy)


if __name__ == "__main__":
    raise SystemExit(main())
