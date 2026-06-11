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


# --- frost-point cooling interlock -----------------------------------
def test_cooldown_gated_by_frost_point(system):
    # Dummy gauge starts at 1e-2 mbar = 1 Pa -> frost point ~-61 C, so the min
    # safe setpoint is ~-56 C: -60 is refused, but -50 (warmer) is allowed.
    system.vacuum.poll()
    assert system.vacuum.pressure_pa == pytest.approx(1.0, rel=0.05)
    assert -58.0 < system.camera.min_safe_setpoint_c() < -53.0
    with pytest.raises(InterlockError):
        system.camera.cooldown(-60.0)
    system.camera.cooldown(-50.0)             # above the frost minimum -> ok
    assert system.devices.camera.is_cooler_on()


def test_deeper_cooling_unlocks_after_pumpdown(system):
    system.devices.vacuum.set_pressure(1.0e-6)   # mbar -> 1e-4 Pa, frost ~-112 C
    system.vacuum.poll()
    assert system.camera.min_safe_setpoint_c() < -100.0
    system.camera.cooldown(-50.0)                # deep cooling now allowed
    assert system.devices.camera.is_cooler_on()


def test_frost_risk_alarm_when_vacuum_degrades_while_cold(system):
    alarms: list[str] = []
    system.safety.add_alarm_listener(alarms.append)
    system.devices.vacuum.set_pressure(1.0e-6); system.vacuum.poll()
    system.camera.cooldown(-50.0)                # cooler on
    system.devices.camera._temp = -50.0          # force the sensor cold
    system.devices.vacuum.set_pressure(1.0e-1); system.vacuum.poll()  # 10 Pa: min safe ~-37
    assert system.safety.check_frost_risk() is True
    assert any("FROST RISK" in a for a in alarms)


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
