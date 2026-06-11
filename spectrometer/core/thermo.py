"""Thermodynamics for the condensation / cooling interlock.

The real constraint on cooling the camera sensor is **frost/condensation**: the
sensor must stay warmer than the frost point of the chamber gas, which is set by
the water-vapour partial pressure. As the chamber pumps down, the frost point
falls and the sensor may go colder.

We only measure *total* pressure, not water partial pressure, so we take the
conservative worst case -- treat the whole measured pressure as water vapour.
The real water partial pressure is lower, so the true frost point is colder than
this estimate; staying above the estimate is therefore always safe.
"""
from __future__ import annotations

import math

# Magnus saturation-over-ice coefficients (es in hPa, T in deg C):
#   es(T) = ICE_A * exp(ICE_B * T / (ICE_C + T))
# Inverting for T (the frost point) given es is exact algebra below.
ICE_A = 6.1115
ICE_B = 22.452
ICE_C = 272.55

# Returned when there is effectively no vacuum (high/invalid pressure): a high
# temperature so the "min safe setpoint" is above any cooling target -> blocked.
NO_VACUUM_FROST_C = 1000.0


def frost_point_c(pressure_pa: float) -> float:
    """Frost point (deg C) assuming all of ``pressure_pa`` is water vapour.

    Conservative: real water partial pressure <= total, so the true frost point
    is <= this. High pressure -> high (positive) frost point (cooling blocked);
    high vacuum -> very negative frost point (deep cooling allowed)."""
    if not (pressure_pa > 0.0) or math.isinf(pressure_pa):
        return NO_VACUUM_FROST_C
    es_hpa = pressure_pa / 100.0
    y = math.log(es_hpa / ICE_A)
    denom = ICE_B - y
    if denom <= 0.0:                       # absurdly high pressure
        return NO_VACUUM_FROST_C
    return ICE_C * y / denom
