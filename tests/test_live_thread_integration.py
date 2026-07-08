"""Integration test: a real QThread + genuine cross-thread queued Qt
connections, exercising the actual mechanism this fix relies on.

Every test in ``test_live.py`` calls ``AcquisitionWorker`` methods as plain
direct Python calls from a background ``threading.Thread`` -- the worker is
never ``moveToThread``'d, so those tests validate the pause/resume and guard
*state machine* but cannot prove the real bug is fixed: that a genuine
queued ``QMetaCallEvent`` posted to the worker's actual owning ``QThread``
(as ``MainWindow`` does for every panel signal) gets drained by
``do_live``'s ``QCoreApplication.processEvents()`` call instead of sitting
stuck until live view stops. This test builds a real ``QThread``, moves the
worker onto it, and drives everything through real queued signal/slot
connections, mirroring ``main_window.py``'s wiring.
"""
from __future__ import annotations

import time

import pytest
from PyQt6.QtCore import QCoreApplication, QMetaObject, QObject, Qt, QThread, pyqtSignal

from spectrometer.core.system import build_system
from spectrometer.gui.worker import AcquisitionWorker


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class _Driver(QObject):
    """Lives on the test thread; its signals are queued across to the
    worker's thread, exactly like MainWindow's re-emit signals."""
    live = pyqtSignal()
    exposure = pyqtSignal(float)
    start_polling = pyqtSignal()


def _wait_until(predicate, timeout_s: float) -> bool:
    """Poll ``predicate`` until it's true or the timeout elapses. Also pumps
    the *test thread's* own event queue each iteration: PyQt routes a signal
    connected to a plain Python callable (e.g. ``list.append``, as opposed to
    a bound method of some QObject) through the thread that made the
    ``connect()`` call -- here, this test thread -- so without this the
    connection would never actually get delivered (we never run a real
    ``app.exec()`` loop in the test)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    QCoreApplication.processEvents()
    return predicate()


def test_exposure_change_delivered_via_real_queued_connection_while_live(qapp):
    sys = build_system(dummy=True)
    sys.open_all()
    thread = QThread()
    try:
        worker = AcquisitionWorker(sys)
        worker.moveToThread(thread)
        thread.start()

        driver = _Driver()
        driver.live.connect(worker.do_live)
        driver.exposure.connect(worker.set_exposure)
        driver.start_polling.connect(worker.start_status_polling)

        statuses: list[dict] = []
        worker.status_updated.connect(statuses.append)
        driver.start_polling.emit()   # queued -> starts the worker's QTimer

        driver.live.emit()   # queued -> worker.do_live on `thread`
        assert _wait_until(lambda: sys.devices.camera._acquiring, 2.0), (
            "live view never started (queued do_live not dispatched)")

        n_before = len(statuses)

        # This is the actual bug being fixed: before the fix, this queued
        # call would sit behind do_live's loop until live view stopped.
        driver.exposure.emit(0.05)
        assert _wait_until(
            lambda: sys.devices.camera.get_exposure() == 0.05, 1.0), (
            "exposure change never took effect -- still queued behind do_live")
        assert sys.devices.camera._acquiring   # acquisition resumed after the change

        # The status-poll QTimer must also have kept ticking (its QTimerEvent
        # needs the same processEvents() pump as the exposure signal).
        assert _wait_until(lambda: len(statuses) > n_before, 1.0)

        worker.stop_live()
        assert _wait_until(lambda: not sys.devices.camera._acquiring, 2.0)

        QMetaObject.invokeMethod(
            worker, "shutdown", Qt.ConnectionType.BlockingQueuedConnection)
    finally:
        thread.quit()
        thread.wait(2000)
        sys.close_all()
