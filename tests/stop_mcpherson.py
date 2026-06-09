"""Emergency stop for the McPherson 789A-4 -- halt motion, leave it idle.

Opens COM5, sends repeated soft-stops (@), disables the home circuit (A0), and
reports the limit (]) and moving (^) status so we can see if it's actually
stopped. Raw serial. Use when the motor is clicking / still being driven.

Run:  python tests/stop_mcpherson.py [COMport]
"""
from __future__ import annotations

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM5"
TERM = b"\r\n"


def comm(ser, cmd, delay=0.15):
    ser.reset_input_buffer()
    ser.write(cmd + TERM)
    time.sleep(delay)
    return ser.read(128)


def main() -> int:
    try:
        ser = serial.Serial(PORT, 9600, timeout=0.3)
    except Exception as exc:
        print("Could not open %s: %s (another process may hold it)." % (PORT, exc))
        return 1
    try:
        time.sleep(0.2)
        print("ident:", comm(ser, b" "))
        for _ in range(5):
            comm(ser, b"@")          # soft stop, repeated
            time.sleep(0.1)
        comm(ser, b"A0")             # disable home circuit
        print("after stop:  ] =", comm(ser, b"]"), "  ^ =", comm(ser, b"^"))
        print("If ] still shows the moving bit (2), the controller is still "
              "driving -- may need a front-panel/power reset.")
        return 0
    finally:
        ser.close()


if __name__ == "__main__":
    raise SystemExit(main())
