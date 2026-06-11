"""Frost-point curve used by the cooling interlock."""
from __future__ import annotations

import pytest

from spectrometer.core.thermo import NO_VACUUM_FROST_C, frost_point_c


def test_frost_point_known_values():
    # Water-over-ice saturation: frost point at a given (assumed-all-water)
    # total pressure. Cross-checked against the saturation table.
    assert frost_point_c(100.0) == pytest.approx(-20.0, abs=0.5)
    assert frost_point_c(27.7) == pytest.approx(-33.0, abs=0.5)
    assert frost_point_c(1.0) == pytest.approx(-61.0, abs=1.0)
    assert frost_point_c(1.0e-2) == pytest.approx(-90.0, abs=1.5)


def test_frost_point_falls_with_pressure():
    assert (frost_point_c(1e5) > frost_point_c(1e2) > frost_point_c(1.0)
            > frost_point_c(1e-2) > frost_point_c(1e-4))


def test_atmosphere_blocks_cooling():
    # At ~1 atm the frost point is well above 0 C, so any cold setpoint is
    # refused (min safe setpoint = frost point + margin).
    assert frost_point_c(1.0e5) > 0.0


def test_no_or_invalid_vacuum_returns_sentinel():
    assert frost_point_c(float("inf")) == NO_VACUUM_FROST_C
    assert frost_point_c(0.0) == NO_VACUUM_FROST_C
    assert frost_point_c(-1.0) == NO_VACUUM_FROST_C
