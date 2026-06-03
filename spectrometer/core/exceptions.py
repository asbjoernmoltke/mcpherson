"""Exceptions for the safety / control layer."""
from __future__ import annotations


class SpectrometerError(Exception):
    """Base class for all application-specific errors."""


class InterlockError(SpectrometerError):
    """A safety interlock refused an operation (e.g. cooling without vacuum)."""


class EStopActive(SpectrometerError):
    """An operation was attempted while the emergency stop was latched."""
