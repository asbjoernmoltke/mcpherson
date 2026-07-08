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
    # Best-effort open: a device that fails to connect starts 'offline' and can
    # be connected later from its panel, rather than blocking the whole GUI.
    log.info("Opening devices (dummy=%s)..." % dummy)
    for name in ("vacuum", "shutter", "laser", "grating", "camera"):
        try:
            getattr(system.devices, name).open()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.error("Could not open %s: %s -- starting offline (use Connect)."
                      % (name, exc))

    app = QApplication(sys.argv)
    window = MainWindow(system, settings)
    window.show()
    try:
        return app.exec()
    finally:
        # Persist settings (the window updates them from the live UI on close).
        settings.save()
        # The close dialog (MainWindow._ask_shutdown_disposition) lets the
        # user skip the camera warm-up to relaunch quickly with the cooler
        # and vacuum pump left running (e.g. after an accidental E-stop).
        if getattr(window, "leave_equipment_running", False):
            log.info("Shutting down: leaving equipment running as chosen at "
                     "close (camera warm-up skipped).")
        else:
            log.info("Shutting down: safe camera warm-up then close devices.")
            try:
                if system.devices.camera.is_cooler_on():
                    system.camera.safe_shutdown()
            except Exception as exc:  # pragma: no cover
                log.error("Safe shutdown error: %s" % exc)
        # Unconditional either way -- just releases serial/SDK handles, does
        # not touch cooler/pump/laser state (every driver's close() is passive).
        system.close_all()
        log.finish()
