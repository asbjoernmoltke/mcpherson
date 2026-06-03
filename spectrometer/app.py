"""Composition root: build the system and launch the GUI."""
from __future__ import annotations

import sys

from .core.system import build_system
from .utilities import log


def run_gui(dummy: bool = False, *, grating_port: str = "COM5") -> int:
    from PyQt6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    system = build_system(dummy=dummy, grating_port=grating_port)
    log.info("Opening devices (dummy=%s)..." % dummy)
    system.open_all()

    app = QApplication(sys.argv)
    window = MainWindow(system)
    window.show()
    try:
        return app.exec()
    finally:
        # Always attempt a safe shutdown: warm the camera before the cooler
        # is cut, then release all devices.
        log.info("Shutting down: safe camera warm-up then close devices.")
        try:
            if system.devices.camera.is_cooler_on():
                system.camera.safe_shutdown()
        except Exception as exc:  # pragma: no cover
            log.error("Safe shutdown error: %s" % exc)
        system.close_all()
        log.finish()
