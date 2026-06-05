"""Composition root: build the system and launch the GUI."""
from __future__ import annotations

import sys

from .core.settings import Settings
from .core.system import build_system_from_settings
from .utilities import log


def run_gui(dummy: bool = False) -> int:
    from PyQt6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    settings = Settings.load()
    system = build_system_from_settings(settings, dummy=dummy)
    log.info("Opening devices (dummy=%s)..." % dummy)
    system.open_all()

    app = QApplication(sys.argv)
    window = MainWindow(system, settings)
    window.show()
    try:
        return app.exec()
    finally:
        # Persist settings (the window updates them from the live UI on close).
        settings.save()
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
