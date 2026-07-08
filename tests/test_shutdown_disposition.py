"""Close-time shutdown-disposition dialog: Safe / Leave Running / Cancel.

``MainWindow._ask_shutdown_disposition`` is stubbed in every test here
instead of showing a real modal ``QMessageBox`` (which would hang a headless
test run waiting for a click that never comes) -- see also the same pattern
in ``tests/smoke_gui.py``.
"""
from __future__ import annotations

import pytest
from PyQt6.QtGui import QCloseEvent

from spectrometer.core.system import build_system
from spectrometer.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    return sys, MainWindow(sys)


def test_leave_running_closes_and_sets_flag(qapp):
    sys, win = _window(qapp)
    win._ask_shutdown_disposition = lambda: "leave_running"
    event = QCloseEvent()
    win.closeEvent(event)
    try:
        assert event.isAccepted()
        assert win.leave_equipment_running is True
        assert not win._thread.isRunning()
        assert not win._aux_thread.isRunning()
    finally:
        sys.close_all()
        win.deleteLater()
        qapp.processEvents()


def test_safe_shutdown_closes_without_flag(qapp):
    sys, win = _window(qapp)
    win._ask_shutdown_disposition = lambda: "safe"
    event = QCloseEvent()
    win.closeEvent(event)
    try:
        assert event.isAccepted()
        assert win.leave_equipment_running is False
        assert not win._thread.isRunning()
        assert not win._aux_thread.isRunning()
    finally:
        sys.close_all()
        win.deleteLater()
        qapp.processEvents()


def test_cancel_leaves_window_open_and_functional(qapp):
    sys, win = _window(qapp)
    try:
        win._ask_shutdown_disposition = lambda: None
        event = QCloseEvent()
        win.closeEvent(event)
        assert not event.isAccepted()
        assert win.leave_equipment_running is False
        # Teardown never ran -- threads/timers still alive, GUI still usable.
        assert win._thread.isRunning()
        assert win._aux_thread.isRunning()

        # A subsequent close still works normally afterward (guard is
        # transient, cancelling once doesn't wedge the window shut forever).
        win._ask_shutdown_disposition = lambda: "safe"
        event2 = QCloseEvent()
        win.closeEvent(event2)
        assert event2.isAccepted()
        assert not win._thread.isRunning()
    finally:
        sys.close_all()
        win.deleteLater()
        qapp.processEvents()
