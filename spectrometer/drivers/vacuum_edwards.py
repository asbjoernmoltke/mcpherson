"""Edwards TIC vacuum-gauge driver (read-only).

Reads the **wide-range gauge** pressure from an Edwards **TIC** (Turbo &
Instrument Controller) over its ASCII serial protocol, to gate camera cooling.
Per the project's locked decision the vacuum layer is READ-ONLY -- we never
command the pumps (nXDS15i backing + EXT turbo); those are handled on isolated
hardware. Optional read-only pump-state getters are provided for display.

TIC protocol (Edwards-owned; see the TIC instruction manual):
  9600 baud, 8N1, commands terminated with CR. Object-ID based:
    ?V<obj>   query value  -> reply ``=V<obj> <data>``
    ?S<obj>   query setup
  Gauges are objects 913/914/915 (gauge 1/2/3). A value reply's data field is
  typically ``<pressure>;<unit-code>;<state>`` (semicolon separated). Error
  replies begin with ``*`` or ``?``.

The exact gauge slot, value format, units, and pump object IDs are confirmed
per-installation with ``tests/discover_edwards.py``; everything here is
configurable so the confirmed values can be set without code changes.
"""
from __future__ import annotations

import threading
from typing import Optional

import serial

from ..utilities import log
from .base import VacuumDriver

# Gauge slot (1/2/3) -> TIC object id.
GAUGE_OBJECTS = {1: 913, 2: 914, 3: 915}

# Pump 'state' codes (object value field 0). Observed on hw 2026-06-10 during a
# pump-down: turbo 0=stopped, 5=starting, 4=running (speed % ramps within
# 'running'); backing 0=stopped, 4=running. Unknown codes shown as "state N".
TURBO_STATE_NAMES = {0: "Stopped", 4: "Running", 5: "Starting"}
BACKING_STATE_NAMES = {0: "Stopped", 4: "Running"}


class EdwardsTIC(VacuumDriver):
    def __init__(self, port: str = "COM7", *, gauge: int = 1,
                 units: str = "Pa", baudrate: int = 9600,
                 terminator: str = "\r", timeout: float = 0.6,
                 turbo_object: int = 904, turbo_speed_object: int = 905,
                 backing_object: int = 910):
        self.port = port
        # Accept a slot (1/2/3) or a raw object id (>=900).
        self.gauge_object = GAUGE_OBJECTS.get(gauge, gauge)
        self._units = units
        self.baudrate = baudrate
        self.terminator = terminator
        self.timeout = timeout
        self.turbo_object = turbo_object
        self.turbo_speed_object = turbo_speed_object  # 905: turbo speed (%)
        self.backing_object = backing_object
        self._ser: Optional[serial.Serial] = None
        self._lock = threading.Lock()

    # --- serial -------------------------------------------------------
    def _comm(self, command: str) -> str:
        if self._ser is None:
            raise RuntimeError("EdwardsTIC port not open.")
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write((command + self.terminator).encode("ascii"))
            raw = self._ser.read_until(self.terminator.encode("ascii"))
        reply = raw.decode("ascii", errors="replace").strip()
        log.debug("EdwardsTIC %s -> %r" % (command, reply))
        return reply

    # --- reply parsing (static for unit testing) ----------------------
    @staticmethod
    def parse_value_reply(reply: str) -> list[str]:
        """Return the ';'-separated data fields of a ``=V<obj> <data>`` reply.

        Raises ValueError on an error/empty reply."""
        if not reply or reply[0] in "*?":
            raise ValueError("TIC error/empty reply: %r" % reply)
        # Strip the ``=V<obj>`` echo up to the first space, if present.
        body = reply.split(" ", 1)[1] if " " in reply else reply
        return [f.strip() for f in body.split(";")]

    @classmethod
    def parse_pressure(cls, reply: str) -> float:
        return float(cls.parse_value_reply(reply)[0])

    # --- lifecycle ----------------------------------------------------
    def open(self) -> None:
        if self.is_connected:
            return
        self._ser = serial.Serial(
            port=self.port, baudrate=self.baudrate, bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE, parity=serial.PARITY_NONE,
            timeout=self.timeout)
        try:
            p = self.read_pressure()
            log.info("EdwardsTIC connected on %s; gauge obj %d reads %.2e %s."
                     % (self.port, self.gauge_object, p, self._units))
        except Exception as exc:
            log.warn("EdwardsTIC opened %s but gauge read failed: %s. Confirm "
                     "port/gauge object with tests/discover_edwards.py."
                     % (self.port, exc))

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None
        log.info("EdwardsTIC closed.")

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    # --- VacuumDriver -------------------------------------------------
    def read_pressure(self) -> float:
        return self.parse_pressure(self._comm("?V%d" % self.gauge_object))

    @property
    def units(self) -> str:
        return self._units

    def get_status(self) -> str:
        if not self.is_connected:
            return "Disconnected"
        try:
            return "%.2e %s" % (self.read_pressure(), self._units)
        except Exception as exc:  # pragma: no cover
            return f"Error: {exc}"

    # --- optional read-only pump status (display only) ----------------
    def read_gauge_state(self) -> Optional[str]:
        try:
            fields = self.parse_value_reply(self._comm("?V%d" % self.gauge_object))
            return fields[-1] if len(fields) > 1 else None
        except Exception:
            return None

    def _state_code(self, obj: int) -> Optional[int]:
        try:
            return int(float(self.parse_value_reply(self._comm("?V%d" % obj))[0]))
        except Exception:
            return None

    def read_turbo_state(self) -> Optional[str]:
        """Turbo status for display, e.g. 'Running, 76%' / 'Starting' / 'Stopped'."""
        st = self._state_code(self.turbo_object)
        if st is None:
            return None
        name = TURBO_STATE_NAMES.get(st, "state %d" % st)
        try:
            speed = float(self.parse_value_reply(
                self._comm("?V%d" % self.turbo_speed_object))[0])
            return "%s, %.0f%%" % (name, speed)
        except Exception:
            return name

    def read_backing_state(self) -> Optional[str]:
        st = self._state_code(self.backing_object)
        if st is None:
            return None
        return BACKING_STATE_NAMES.get(st, "state %d" % st)

    # --- pump CONTROL (opt-in; interlocks live in VacuumController) ----
    def supports_control(self) -> bool:
        return True

    def _command(self, obj: int, value: int) -> None:
        """Send `!C<obj> <value>` and raise on rejection. Reply is
        `*C<obj> <error>`; error 0 = accepted (manual Table 3). Error 5 means
        the TIC is in parallel control mode and ignores serial start/stop."""
        reply = self._comm("!C%d %d" % (obj, value))
        parts = reply.replace(";", " ").split()
        try:
            err = int(parts[-1]) if parts else None
        except ValueError:
            err = None
        if err != 0:
            hint = (" -- the TIC is in PARALLEL control mode; set it to serial "
                    "control to allow this." if err == 5 else "")
            raise RuntimeError("TIC rejected !C%d %d (error %s)%s: %r"
                               % (obj, value, err, hint, reply))

    def set_turbo(self, on: bool) -> None:
        self._command(self.turbo_object, 1 if on else 0)

    def set_backing(self, on: bool) -> None:
        self._command(self.backing_object, 1 if on else 0)

    def turbo_state_code(self) -> Optional[int]:
        return self._state_code(self.turbo_object)

    def backing_state_code(self) -> Optional[int]:
        return self._state_code(self.backing_object)
