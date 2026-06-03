"""Safety-layer tests: E-stop behaviour and the vacuum/cooling interlock.

Run with: pytest -q   (from the repo root)
These use the all-dummy system, so they need no hardware.
"""
from __future__ import annotations

import pytest

from spectrometer.core.exceptions import EStopActive, InterlockError
from spectrometer.core.system import build_system


@pytest.fixture
def system():
    sys = build_system(dummy=True, cooling_threshold=1.0e-4)
    sys.open_all()
    yield sys
    sys.close_all()


# --- vacuum / cooling interlock --------------------------------------
def test_cooldown_refused_when_vacuum_too_high(system):
    # Dummy gauge starts at a poor vacuum (1e-2 mbar) -> cooling refused.
    assert not system.vacuum.vacuum_ok
    with pytest.raises(InterlockError):
        system.camera.cooldown(-60.0)
    with pytest.raises(InterlockError):
        system.safety.assert_can_cool()


def test_cooldown_permitted_after_pumpdown(system):
    system.devices.vacuum.set_pressure(1.0e-6)  # simulate pump-down
    assert system.vacuum.vacuum_ok
    system.safety.assert_can_cool()       # must not raise
    system.camera.cooldown(-60.0)         # must not raise
    assert system.devices.camera.is_cooler_on()


def test_vacuum_lost_while_cold_raises_alarm(system):
    alarms: list[str] = []
    system.safety.add_alarm_listener(alarms.append)
    system.devices.vacuum.set_pressure(1.0e-6)
    system.camera.cooldown(-60.0)          # cooler now on
    system.devices.vacuum.set_pressure(1.0e-1)  # vacuum lost
    assert system.safety.check_vacuum_while_cold() is True
    assert any("VACUUM LOST" in a for a in alarms)


# --- emergency stop ---------------------------------------------------
def test_estop_closes_shutter_disables_laser_and_latches(system):
    system.shutter.open()
    system.laser.enable()
    assert system.shutter.is_open and system.laser.is_enabled

    system.safety.estop()

    assert not system.shutter.is_open      # beam blocked
    assert not system.laser.is_enabled     # laser off
    assert system.safety.is_estopped       # latched
    assert system.abort.is_set()           # abort flag propagated


def test_acquire_refused_while_estopped(system):
    system.safety.estop()
    with pytest.raises(EStopActive):
        system.sync.acquire(1)


def test_estop_reset_clears_flag(system):
    system.safety.estop()
    system.safety.reset_estop()
    assert not system.safety.is_estopped
    assert not system.abort.is_set()


def test_sync_acquire_brackets_shutter(system):
    # After a normal synced acquisition the shutter must end up closed.
    system.devices.vacuum.set_pressure(1.0e-6)
    frames = system.sync.acquire(1)
    assert frames.shape[0] == 1
    assert not system.shutter.is_open
