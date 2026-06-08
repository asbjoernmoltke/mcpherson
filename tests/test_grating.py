"""Grating controller hardening tests (homed-state, limits, validation)."""
from __future__ import annotations

import pytest

from spectrometer.controllers.grating import GratingController
from spectrometer.core.calibration import default_calibration
from spectrometer.core.exceptions import NotHomedError, OutOfRangeError
from spectrometer.drivers.mcpherson import MP_789A_4, DummyGrating


# --- 789A-4 status parsing (the substring-bug regression guard) -------
def test_parse_status_is_integer_not_substring():
    p = MP_789A_4._parse_status
    assert p(b"]   0 \r\n") == 0
    assert p(b"]   32 \r\n") == 32
    assert p(b"]   34 \r\n") == 34          # home + moving
    assert p(b"^   2 \r\n") == 2
    assert p(b"]   128 \r\n") == 128


def test_status_bits_distinguish_home_from_moving():
    # The old `'2' in rx` check misfired on a status of 32 (contains '2').
    assert not (MP_789A_4.ST_HOME & MP_789A_4.ST_MOVING)
    assert not (32 & MP_789A_4.ST_MOVING)       # on-flag is NOT "moving"
    assert 34 & MP_789A_4.ST_MOVING             # home+moving IS moving
    # The old `'64' in rx` check missed 66 (upper-limit + moving).
    assert 66 & MP_789A_4.ST_UPPER
    assert 130 & MP_789A_4.ST_LOWER             # 128 + moving


def _controller():
    cal = default_calibration("1200g/mm")
    return GratingController(DummyGrating(), calibration=cal), cal


# --- homed-state gate -------------------------------------------------
def test_absolute_move_refused_until_homed():
    ctl, _ = _controller()
    assert not ctl.is_homed
    with pytest.raises(NotHomedError):
        ctl.move_to_position(1000)
    with pytest.raises(NotHomedError):
        ctl.move_to_wavelength(400.0)


def test_home_sets_homed_and_enables_moves():
    ctl, _ = _controller()
    assert ctl.home() is True
    assert ctl.is_homed
    ctl.move_to_position(1000)            # within limits, no raise
    assert ctl.position == 1000


def test_stop_clears_homed_reference():
    ctl, _ = _controller()
    ctl.home()
    assert ctl.is_homed
    ctl.stop()
    assert not ctl.is_homed
    with pytest.raises(NotHomedError):
        ctl.move_to_position(0)


# --- calibrated limits ------------------------------------------------
def test_position_out_of_range_rejected():
    ctl, cal = _controller()
    ctl.home()
    lo, hi = cal.position_limits
    with pytest.raises(OutOfRangeError):
        ctl.move_to_position(hi + 1)
    with pytest.raises(OutOfRangeError):
        ctl.move_to_position(lo - 1)
    ctl.move_to_position(hi)              # boundary is allowed


def test_wavelength_out_of_range_rejected():
    ctl, cal = _controller()
    ctl.home()
    lo, hi = cal.wavelength_limits()
    with pytest.raises(OutOfRangeError):
        ctl.move_to_wavelength(hi + 50.0)
    with pytest.raises(OutOfRangeError):
        ctl.move_to_wavelength(lo - 50.0)


def test_valid_wavelength_move_lands_near_target():
    ctl, cal = _controller()
    ctl.home()
    ctl.move_to_wavelength(400.0)
    # Position should map back to ~400 nm centre wavelength.
    assert cal.center_wavelength(ctl.position) == pytest.approx(400.0, abs=0.5)


def test_unbounded_without_calibration():
    ctl = GratingController(DummyGrating())   # no calibration
    ctl.home()
    ctl.move_to_position(5000)                # no limit validation
    assert ctl.position == 5000
