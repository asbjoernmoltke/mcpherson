"""Exceptions for the safety / control layer."""
from __future__ import annotations


class SpectrometerError(Exception):
    """Base class for all application-specific errors."""


class InterlockError(SpectrometerError):
    """A safety interlock refused an operation (e.g. cooling without vacuum)."""


class EStopActive(SpectrometerError):
    """An operation was attempted while the emergency stop was latched."""


class NotHomedError(SpectrometerError):
    """An absolute grating move was requested before the grating was homed.

    Absolute step positions are only meaningful relative to the home flag, so
    the grating must be homed before any position/wavelength move."""


class OutOfRangeError(SpectrometerError):
    """A move/wavelength target lies outside the calibrated limits."""
