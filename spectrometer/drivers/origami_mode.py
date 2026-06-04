"""Detect and switch the Origami XPS serial interface mode.

The Origami exposes one RS-232 port as either CLI (38400 baud, ASCII) or
NKTPBus/Interbus (115200 baud, binary). They are mutually exclusive; the
active interface is Interbus register ``0x39`` on module type ``0x95``
(0 = NKTPBus, 1 = CLI).

* :func:`is_cli_responding` -- non-destructive probe (open at 38400, ask for
  status, look for the ``ly_oxp2`` echo).
* :func:`switch_to_cli` -- via NKTPDLL, write reg 0x39 := 1 (NKTPBus -> CLI).
* :func:`switch_to_nktpbus` -- pure CLI command ``ly_oxp2_nktpbus=1``.
* :func:`ensure_mode` -- bring the laser into the desired mode if needed.

Adapted from the NKT SDK examples / pyccapt helpers; the protocols are NKT's.
"""
from __future__ import annotations

import time

import serial

from ..utilities import log

OXPS_MODULE_TYPE = 0x95
INTERFACE_MODE_REGISTER = 0x39
MODE_NKTPBUS = 0
MODE_CLI = 1
CLI_BAUD = 38400
_PROBE_ADDRESSES = (15, 1, 16, 10)


class OrigamiModeError(RuntimeError):
    pass


def is_cli_responding(port: str, *, timeout_s: float = 1.5) -> bool:
    """True iff the laser replies to a CLI status query (=> in CLI mode)."""
    try:
        with serial.Serial(port=port, baudrate=CLI_BAUD,
                           bytesize=serial.EIGHTBITS, stopbits=serial.STOPBITS_ONE,
                           rtscts=False, timeout=timeout_s) as ser:
            ser.reset_input_buffer()
            ser.write(b"ly_oxp2_dev_status\n")
            deadline = time.time() + timeout_s
            buf = b""
            while time.time() < deadline:
                chunk = ser.read(64)
                if chunk:
                    buf += chunk
                    if b"\n" in buf:
                        break
                elif buf:
                    break
            return b"ly_oxp2" in buf
    except Exception:
        return False


def _find_address(nkt, port: str) -> int:
    for dev_id in _PROBE_ADDRESSES:
        try:
            result, dev_type = nkt.deviceGetType(port, dev_id)
        except Exception:
            continue
        if result == 0 and dev_type and (dev_type & 0xFF) == OXPS_MODULE_TYPE:
            return dev_id
    raise OrigamiModeError(
        "No Origami OXPS (type 0x95) found on %s via NKTPBus." % port)


def switch_to_cli(port: str, *, settle_seconds: float = 1.0) -> int:
    """NKTPBus -> CLI: write reg 0x39 = 1 via NKTPDLL. Returns device address."""
    from .laser_nkt import _load_nkt  # reuse the SDK loader
    nkt = _load_nkt(_default_sdk_path())
    result = nkt.openPorts(port, 1, 0)
    if result != 0:
        raise OrigamiModeError("openPorts(%s) failed: %s (NKT CONTROL open, or "
                               "already in CLI mode?)" % (port, nkt.PortResultTypes(result)))
    try:
        dev_id = _find_address(nkt, port)
        wr = nkt.registerWriteU8(port, dev_id, INTERFACE_MODE_REGISTER, MODE_CLI, -1)
        if wr != 0:
            raise OrigamiModeError("reg 0x39:=1 failed: %s" % nkt.RegisterResultTypes(wr))
        time.sleep(settle_seconds)
        log.info("Origami switched to CLI mode (port %s, addr 0x%02X)." % (port, dev_id))
        return dev_id
    finally:
        try:
            nkt.closePorts(port)
        except Exception:
            pass


def switch_to_nktpbus(port: str) -> None:
    """CLI -> NKTPBus: pure CLI command (no DLL needed)."""
    with serial.Serial(port=port, baudrate=CLI_BAUD, bytesize=serial.EIGHTBITS,
                       stopbits=serial.STOPBITS_ONE, rtscts=False, timeout=1.0) as ser:
        ser.write(b"ly_oxp2_nktpbus=1\n")
        time.sleep(0.2)
        try:
            ser.read(ser.in_waiting or 0)
        except Exception:
            pass
    log.info("Origami switched to NKTPBus mode (port %s)." % port)


def ensure_mode(port: str, target: str) -> None:
    """Bring the laser into ``target`` mode ('cli' or 'nktpbus') if needed."""
    target = target.lower()
    cli_now = is_cli_responding(port)
    if target == "cli":
        if cli_now:
            log.info("Origami already in CLI mode on %s." % port)
        else:
            log.warn("Origami not responding to CLI on %s; switching from "
                     "NKTPBus." % port)
            switch_to_cli(port)
    elif target == "nktpbus":
        if cli_now:
            switch_to_nktpbus(port)
        else:
            log.info("Origami appears already in NKTPBus mode on %s." % port)
    else:
        raise ValueError("target must be 'cli' or 'nktpbus'.")


def _default_sdk_path() -> str:
    from .laser_nkt import DEFAULT_SDK_PATH
    return DEFAULT_SDK_PATH
