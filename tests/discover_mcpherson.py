"""Read-only McPherson 789A-4 discovery probe -- RUN AT THE CONTROLLER.

SAFE: identify + status only. Sends ONLY the init handshake and the read
queries ``]`` (limit/home status) and ``^`` (moving status). It NEVER issues a
motion command (no ``+`` / ``-`` / ``M`` / ``F`` / ``A`` / ``@`` / ``G``), so
the grating does not move. Use this to confirm the COM port, the controller
firmware reply, and where the mechanism currently sits (home flag / limits)
*before* attempting a home or any move.

Framing matches the driver: every command is terminated with CRLF and we read
up to 128 bytes after a short settle (see ``utilities/safe_serial``).

Run:  python tests/discover_mcpherson.py [COMport]   (default COM5)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

from spectrometer.utilities import ports_finder  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
TERM = b"\r\n"

# ] limit-status reply is a decimal bit-sum; these are the documented bits.
LIMIT_BITS = {
    2: "MOVING",
    32: "HOME switch blocked",
    64: "UPPER limit switch",
    128: "LOWER limit switch",
}


def comm(ser, cmd: bytes, delay: float = 0.15) -> bytes:
    ser.reset_input_buffer()
    ser.write(cmd + TERM)
    time.sleep(delay)
    return ser.read(128)


def _first_int(reply: bytes):
    """Extract the first integer token from a controller reply, or None."""
    digits = b""
    for ch in reply:
        c = chr(ch)
        if c.isdigit():
            digits += bytes([ch])
        elif digits:
            break
    return int(digits) if digits else None


def _decode_limits(value: int) -> str:
    if value == 0:
        return "idle, off home & limits"
    hits = [name for bit, name in LIMIT_BITS.items() if value & bit]
    return " + ".join(hits) if hits else "unrecognised bit pattern"


def main() -> int:
    print("=== McPherson 789A-4 probe on %s (9600 8N1, READ-ONLY, no motion) ==="
          % PORT)

    print("\n-- Available serial ports --")
    for line in ports_finder.find_com_ports():
        marker = "  <-- target" if line.startswith(PORT + " ") else ""
        print("  " + line + marker)

    try:
        ser = serial.Serial(PORT, baudrate=9600, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
                            timeout=0.3)
    except Exception as exc:
        print("\nCould not open %s: %s" % (PORT, exc))
        print("Confirm the port above; another program (the GUI?) may hold it.")
        return 1

    try:
        time.sleep(0.2)  # let the controller settle after the port opens

        print("\n-- Identify (init handshake, bare space) --")
        rx = comm(ser, b" ")
        print("  ' ' (init) -> %r" % rx)
        if b"v2.55" in rx:
            print("  OK: McPherson 789A-4 found (firmware v2.55).")
        elif b"#" in rx:
            print("  OK: 789A-4 responding (already initialised).")
        else:
            print("  ?? Unexpected reply -- is this the 789A-4 / right port?")

        print("\n-- Limit / home status ( ] ) --")
        rx = comm(ser, b"]")
        val = _first_int(rx)
        print("  ']' -> %r   parsed=%s" % (rx, val))
        if val is not None:
            print("       => %s" % _decode_limits(val))

        print("\n-- Moving status ( ^ ) --")
        rx = comm(ser, b"^")
        val = _first_int(rx)
        print("  '^' -> %r   parsed=%s   (0 = stopped)" % (rx, val))

        print("\nNo motion was commanded. Next, once the reply above looks "
              "sane, we can home and verify steps/rev + direction.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
