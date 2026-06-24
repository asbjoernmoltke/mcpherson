"""Diagnose why the Origami CLI fields are blank -- READ-ONLY, switches nothing.

Opens the CLI port (38400) and prints the raw replies to the status/query
commands the GUI relies on. If the laser is in NKTPBus mode the CLI replies are
empty/garbage -> that is why every field shows blank, and the laser must be put
into CLI mode (reg 0x39=1) first.

Run:  python tests/probe_origami_cli.py [COMport]   (default COM6)
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM6"
CLI_BAUD = 38400
QUERIES = ["ly_oxp2_dev_status", "ly_oxp2_mode?", "e_power?", "e_freq?",
           "e_div?", "e_mlp?", "ly_oxp2_power?"]


def txn(ser, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + "\n").encode("ascii"))
    deadline = time.time() + 0.6
    buf = b""
    time.sleep(0.08)
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
            time.sleep(0.03)
        elif buf:
            break
        else:
            time.sleep(0.02)
    return buf.decode("ascii", errors="replace").strip()


def main() -> int:
    print("=== Origami CLI probe on %s (read-only, 38400) ===" % PORT)
    try:
        ser = serial.Serial(PORT, baudrate=CLI_BAUD, bytesize=serial.EIGHTBITS,
                            stopbits=serial.STOPBITS_ONE, rtscts=False, timeout=0.6)
    except Exception as exc:
        print("Could not open %s: %s" % (PORT, exc))
        print("(If the app has the laser connected, disconnect it first so the "
              "port is free.)")
        return 1
    try:
        for cmd in QUERIES:
            print("  %-20s -> %r" % (cmd, txn(ser, cmd)))
        print("\nIf 'ly_oxp2_dev_status' is empty/garbage, the laser is NOT in "
              "CLI mode (probably NKTPBus). It must be switched to CLI mode "
              "(reg 0x39=1) before our CLI driver can read it.")
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
