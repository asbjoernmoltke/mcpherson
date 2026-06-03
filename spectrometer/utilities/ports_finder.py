"""Serial-port discovery helpers.

Trimmed from the original project file: the Thorlabs APT / KST101 discovery
and virtual-port helpers were dropped along with their heavy import-time
dependencies. Only the COM/serial enumeration used by the device drivers
remains.
"""
from __future__ import annotations

import glob
import sys

import serial
import serial.tools.list_ports


def find_com_ports() -> list[str]:
    """Return human-readable descriptions of the available COM ports."""
    ports = serial.tools.list_ports.comports()
    return [f"{port} {desc} {hwid}" for port, desc, hwid in sorted(ports)]


def find_serial_ports() -> list[str]:
    """List serial port names that can actually be opened.

    :raises EnvironmentError: on unsupported platforms.
    :returns: a list of the serial ports available on the system.
    """
    if sys.platform.startswith("win"):
        ports = ["COM%s" % (i + 1) for i in range(256)]
    elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
        ports = glob.glob("/dev/tty[A-Za-z]*")
    elif sys.platform.startswith("darwin"):
        ports = glob.glob("/dev/tty.*")
    else:
        raise EnvironmentError("Unsupported platform")

    result: list[str] = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result
