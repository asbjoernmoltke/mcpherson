"""NKT Photonics laser driver (via the vendor NKTPDLL SDK).

Implements :class:`~spectrometer.drivers.base.LaserDriver` for an NKT laser
using the register-based Interbus protocol exposed by ``NKTPDLL.dll`` through
the vendor's ``NKTP_DLL.py`` Python wrapper.

This deployment targets an **NKT Origami XP**, which runs on the NKT
**"Aeropulse mainboard"** (Interbus module type ``0x9D``). All controls go
through a SINGLE open connection (one ``NKTLaser`` instance / one
``openPorts``) -- the Interbus does not allow a second process to open the
same port, so every control (emission, power, pulse-picker, rep-rate, status)
is consolidated here.

Register map (from the SDK ``Register Files`` for the aeroPulse mainboard;
verify with a discovery scan once the laser is connected):

* ``0x30`` Emission  : 0=off, 1=seed, 2=preamp, 3=booster  (U8)
* ``0x34`` Pulse-Picker ratio ("Times", the rep-rate divider)  (U16)
* ``0x37`` Output level (%) in 0.1 % units  (U16)
* ``0x32`` Interlock (>0 = reset)  ;  ``0x66`` status bits  ;  ``0x67`` error

SAFETY: ``disable()`` writes ``0`` to the emission register -- OFF=0 is
consistent across all NKT products, so the E-stop is safe even if the precise
model/map differs. ``open()``/``close()`` force standby so attaching or
shutting down never leaves the beam on. Long emission stages and power are
configurable via :class:`NKTRegisterMap`; switch presets if your unit differs.

The vendor wrapper is imported lazily from ``sdk_path`` so the dummy/offline
paths never require the DLL.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

from ..utilities import log
from .base import STANDARD_REP_RATES_HZ, LaserDriver

DEFAULT_SDK_PATH = r"C:\Users\Public\Documents\NKT Photonics\SDK"
_REG_SUCCESS = 0  # RegResultSuccess

# Discrete amplifier repetition rates for the Origami XP (50-1000 kHz).
ORIGAMI_REP_RATES_HZ = STANDARD_REP_RATES_HZ


@dataclass(frozen=True)
class NKTRegisterMap:
    """Register layout + emission encoding for one NKT product family."""
    name: str
    module_type: Optional[int]      # Interbus device type, for address auto-detect
    address: int = 15               # fallback module address if not auto-detected
    emission_register: int = 0x30
    emission_off: int = 0x00
    emission_on: int = 0x03         # value for full emission (booster)
    emission_seed: Optional[int] = 0x01
    emission_preamp: Optional[int] = 0x02
    power_register: Optional[int] = 0x37
    power_pct_per_lsb: float = 0.1  # register LSB -> percent
    pulse_picker_register: Optional[int] = 0x34
    # Amplifier repetition-rate register: NOT yet identified for the aeroPulse
    # mainboard / Origami (rep rate is a discrete amplifier setting separate
    # from the pulse picker). Left None until confirmed from NKT CONTROL/docs.
    rep_rate_register: Optional[int] = None
    rep_rate_hz_per_lsb: float = 1.0
    status_register: Optional[int] = 0x66
    interlock_register: Optional[int] = 0x32


# Presets. Default targets the Origami XP (aeroPulse mainboard, type 0x9D).
AEROPULSE_MAINBOARD = NKTRegisterMap(
    name="Aeropulse mainboard (0x9D) / Origami XP", module_type=0x9D,
    emission_on=0x03, power_register=0x37, pulse_picker_register=0x34)
SUPERK_FIANIUM = NKTRegisterMap(
    name="SuperK Extreme / Fianium (0x60)", module_type=0x60,
    emission_on=0x03, power_register=0x37, pulse_picker_register=0x34)
FS50_EXAMPLE = NKTRegisterMap(
    name="aeroPulse FS50 (example map)", module_type=None,
    emission_on=0x04, emission_seed=None, emission_preamp=None,
    power_register=0x99, pulse_picker_register=None)

# Status-bit meanings for the aeroPulse/SuperK status register (0x66).
_STATUS_BITS = {
    0: "emission", 1: "interlock_off", 2: "interlock_power_failure",
    3: "interlock_loop_off", 4: "external_disable", 5: "supply_voltage_low",
    6: "module_temp_range", 15: "error_present",
}


def _load_nkt(sdk_path: str):
    """Import and return the vendor ``NKTP_DLL`` module (sets NKTP_SDK_PATH)."""
    os.environ.setdefault("NKTP_SDK_PATH", sdk_path)
    wrapper_dir = os.path.join(sdk_path, "Examples", "DLL_Example_Python")
    if wrapper_dir not in sys.path:
        sys.path.append(wrapper_dir)
    import NKTP_DLL  # noqa: E402 (deliberate lazy import)
    return NKTP_DLL


class NKTLaser(LaserDriver):
    def __init__(self, port: Optional[str] = None, *,
                 regmap: NKTRegisterMap = AEROPULSE_MAINBOARD,
                 sdk_path: str = DEFAULT_SDK_PATH,
                 full_scale_energy_uj: float = 40.0):
        self.port = port
        self.regmap = regmap
        self.address = regmap.address
        self.sdk_path = sdk_path
        # Provisional pulse energy (uJ) at 100 % of the relative power scale;
        # calibrate against a power meter. See OrigamiCLI for the same note.
        self.full_scale_energy_uj = full_scale_energy_uj
        self._nkt = None
        self._connected = False

    # --- low-level helpers --------------------------------------------
    def _api(self):
        if self._nkt is None:
            self._nkt = _load_nkt(self.sdk_path)
        return self._nkt

    def _write_u8(self, reg: int, value: int, *, what: str, raise_on_fail=True):
        nkt = self._api()
        result = nkt.registerWriteU8(self.port, self.address, reg, value, -1)
        if result != _REG_SUCCESS:
            msg = "NKTLaser %s failed: %s" % (what, nkt.RegisterResultTypes(result))
            if raise_on_fail:
                raise RuntimeError(msg)
            log.error(msg)
        return result

    def _write_u16(self, reg: int, value: int, *, what: str):
        nkt = self._api()
        result = nkt.registerWriteU16(self.port, self.address, reg, value, -1)
        if result != _REG_SUCCESS:
            raise RuntimeError("NKTLaser %s failed: %s"
                               % (what, nkt.RegisterResultTypes(result)))

    def _read_u8(self, reg: int) -> Optional[int]:
        nkt = self._api()
        result, value = nkt.registerReadU8(self.port, self.address, reg, -1)
        return value if result == _REG_SUCCESS else None

    def _read_u16(self, reg: int) -> Optional[int]:
        nkt = self._api()
        result, value = nkt.registerReadU16(self.port, self.address, reg, -1)
        return value if result == _REG_SUCCESS else None

    def find_modules(self) -> dict[int, int]:
        """Scan open ports, return {address: device_type}; logs findings."""
        nkt = self._api()
        nkt.openPorts(nkt.getAllPorts(), 1, 0)
        found: dict[int, int] = {}
        for portname in [p for p in nkt.getOpenPorts().split(",") if p]:
            _result, dev_list = nkt.deviceGetAllTypesV2(portname)
            for addr, dtype in enumerate(dev_list):
                if dtype != 0:
                    log.info("NKT module on %s: type 0x%04X at address %d"
                             % (portname, dtype, addr))
                    if self.port is None or portname == self.port:
                        found[addr] = dtype
        return found

    # --- Driver lifecycle ---------------------------------------------
    def open(self) -> None:
        nkt = self._api()
        modules = self.find_modules()
        open_ports = [p for p in nkt.getOpenPorts().split(",") if p]
        if self.port is None and open_ports:
            self.port = open_ports[0]
        if self.port is None:
            raise RuntimeError("NKTLaser: no NKT port found. Is the laser "
                               "connected and powered?")
        # Auto-detect the module address by its Interbus type when known.
        if self.regmap.module_type is not None:
            matches = [a for a, t in modules.items() if t == self.regmap.module_type]
            if matches:
                self.address = matches[0]
                log.info("NKTLaser: found %s at address %d on %s."
                         % (self.regmap.name, self.address, self.port))
            else:
                log.warn("NKTLaser: module type 0x%04X (%s) not found among %s; "
                         "using fallback address %d. Confirm the model."
                         % (self.regmap.module_type, self.regmap.name,
                            {a: hex(t) for a, t in modules.items()}, self.address))
        self._connected = True
        # Passive connect: do NOT change emission, so the connection can be
        # handed off to the vendor software untouched. Use disable()/E-stop to
        # change emission explicitly.
        log.info("NKTLaser connected on %s (address %d); state left unchanged."
                 % (self.port, self.address))

    def close(self) -> None:
        # Passive: leave emission as-is; just release the port.
        if self._connected:
            try:
                self._nkt.closePorts(self.port or "")
            except Exception as exc:  # pragma: no cover
                log.error("NKTLaser closePorts error: %s" % exc)
        self._connected = False
        log.info("NKTLaser closed (state left unchanged).")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- emission control ---------------------------------------------
    def enable(self) -> None:
        """Start full emission (booster stage)."""
        self._write_u8(self.regmap.emission_register, self.regmap.emission_on,
                       what="enable")
        log.info("NKTLaser: emission ON (value %d)." % self.regmap.emission_on)

    def disable(self) -> None:
        """E-stop fast path: best-effort, retried, never raises."""
        for attempt in range(3):
            result = self._write_u8(self.regmap.emission_register,
                                    self.regmap.emission_off,
                                    what="disable", raise_on_fail=False)
            if result == _REG_SUCCESS:
                log.info("NKTLaser: emission OFF (standby).")
                return
            time.sleep(0.02)
        log.fatal("NKTLaser: FAILED to confirm emission OFF after retries!")

    def set_emission_stage(self, stage: str) -> None:
        """Set a specific emission stage: 'off' | 'seed' | 'preamp' | 'booster'."""
        rm = self.regmap
        values = {"off": rm.emission_off, "seed": rm.emission_seed,
                  "preamp": rm.emission_preamp, "booster": rm.emission_on}
        if stage not in values or values[stage] is None:
            raise ValueError("Unsupported emission stage %r for %s"
                             % (stage, rm.name))
        self._write_u8(rm.emission_register, values[stage],
                       what="set_emission_stage(%s)" % stage)

    @property
    def is_enabled(self) -> bool:
        value = self._read_u8(self.regmap.emission_register)
        return value is not None and value != self.regmap.emission_off

    @property
    def emission_stage(self) -> str:
        value = self._read_u8(self.regmap.emission_register)
        rm = self.regmap
        return {rm.emission_off: "off", rm.emission_seed: "seed",
                rm.emission_preamp: "preamp", rm.emission_on: "booster"
                }.get(value, "unknown")

    # --- power --------------------------------------------------------
    def set_power_percent(self, percent: float) -> None:
        if self.regmap.power_register is None:
            raise RuntimeError("Power control not mapped for %s" % self.regmap.name)
        percent = max(0.0, min(100.0, percent))
        raw = int(round(percent / self.regmap.power_pct_per_lsb))
        self._write_u16(self.regmap.power_register, raw, what="set_power")
        log.info("NKTLaser: power set to %.1f %%." % percent)

    def read_power_percent(self) -> Optional[float]:
        if self.regmap.power_register is None:
            return None
        raw = self._read_u16(self.regmap.power_register)
        return None if raw is None else raw * self.regmap.power_pct_per_lsb

    # --- pulse energy (uJ) via the relative power scale (provisional cal) --
    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        return None if self.regmap.power_register is None else self.full_scale_energy_uj

    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        energy_uj = max(0.0, min(self.full_scale_energy_uj, energy_uj))
        self.set_power_percent(energy_uj / self.full_scale_energy_uj * 100.0)

    def read_pulse_energy_uj(self) -> Optional[float]:
        pct = self.read_power_percent()
        return None if pct is None else pct / 100.0 * self.full_scale_energy_uj

    # --- pulse picking / repetition rate ------------------------------
    def set_pulse_picker_ratio(self, ratio: int) -> None:
        """Pulse-picker divider (register 0x34). Output rep rate = seed / ratio.
        ratio=1 passes every pulse; larger ratios lower the rep rate."""
        if self.regmap.pulse_picker_register is None:
            raise RuntimeError("Pulse picker not mapped for %s" % self.regmap.name)
        if ratio < 1:
            raise ValueError("Pulse-picker ratio must be >= 1.")
        self._write_u16(self.regmap.pulse_picker_register, int(ratio),
                        what="set_pulse_picker_ratio")
        log.info("NKTLaser: pulse-picker ratio = %d." % ratio)

    def read_pulse_picker_ratio(self) -> Optional[int]:
        if self.regmap.pulse_picker_register is None:
            return None
        return self._read_u16(self.regmap.pulse_picker_register)

    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        """Discrete amplifier rep rates (50-1000 kHz). The GUI gates the
        control on ``read_repetition_rate_hz`` being non-None, which requires
        ``rep_rate_register`` to be identified (TBD for the Origami)."""
        return ORIGAMI_REP_RATES_HZ

    def read_repetition_rate_hz(self) -> Optional[float]:
        """Amplifier repetition rate (a discrete setting, separate from the
        pulse picker). Returns None until ``rep_rate_register`` is identified
        for this module -- the GUI then greys out the control."""
        if self.regmap.rep_rate_register is None:
            return None
        raw = self._read_u16(self.regmap.rep_rate_register)
        return None if raw is None else raw * self.regmap.rep_rate_hz_per_lsb

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        """Snap to the nearest allowed discrete rate and apply it."""
        if self.regmap.rep_rate_register is None:
            raise RuntimeError(
                "Origami repetition-rate register not yet identified; cannot "
                "set rep rate. Use the pulse-picker ratio, or supply "
                "NKTRegisterMap.rep_rate_register once known.")
        applied = min(ORIGAMI_REP_RATES_HZ, key=lambda r: abs(r - target_hz))
        raw = int(round(applied / self.regmap.rep_rate_hz_per_lsb))
        self._write_u16(self.regmap.rep_rate_register, raw, what="set_rep_rate")
        log.info("NKTLaser: rep rate %.0f kHz." % (applied / 1e3))
        return applied

    # --- status -------------------------------------------------------
    def read_status_bits(self) -> dict[str, bool]:
        if self.regmap.status_register is None:
            return {}
        raw = self._read_u16(self.regmap.status_register)
        if raw is None:
            return {}
        return {name: bool(raw & (1 << bit)) for bit, name in _STATUS_BITS.items()}

    def reset_interlock(self) -> None:
        if self.regmap.interlock_register is None:
            raise RuntimeError("Interlock register not mapped for %s" % self.regmap.name)
        self._write_u16(self.regmap.interlock_register, 1, what="reset_interlock")
        log.info("NKTLaser: interlock reset requested.")

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        try:
            stage = self.emission_stage
            ratio = self.read_pulse_picker_ratio()
            power = self.read_power_percent()
            parts = [stage]
            if power is not None:
                parts.append("%.0f%%" % power)
            if ratio:
                parts.append("PP 1/%d" % ratio)
            return ", ".join(parts)
        except Exception as exc:  # pragma: no cover
            return f"Error: {exc}"


# Origami XPS status-bit meanings (register 0x66, U32).
_ORIGAMI_STATUS_BITS = {
    0: "emission_on", 1: "main_interlock_open", 2: "switching_prr",
    3: "aux_interlock_open", 5: "supply_voltage_low", 6: "temp_out_of_range",
    14: "module_error", 15: "error_present",
}


class OrigamiXPS(LaserDriver):
    """NKT Origami XPS regenerative-amplifier femtosecond laser (module 0x95).

    Confirmed live from the unit (read-only dump): emission is a state machine
    (``0x30`` target, state 1 = OFF), a separate internal shutter (``0x34``),
    a discrete rep-rate index (``0x35``; index 0 = 50 kHz), and a U32
    frequency-division pulse picker (``0x36``, 1..1,000,000).

    SAFETY: ``disable()`` closes the internal shutter (0x34=0) AND sets the FSM
    target to OFF (0x30=1) -- both verified as the standby/closed values, so
    the E-stop path is unambiguous. ``enable()`` targets the RUN state, which
    is still to be CONFIRMED against the Origami manual (valid targets
    [1,3,5,6]); set ``FSM_RUN`` accordingly. Power full-scale (0x05 = 4000 =>
    100 %) and the rep-rate index->Hz table beyond index 0 are best-effort and
    flagged for confirmation.
    """

    MODULE_TYPE = 0x95
    REG_FSM_STATE = 0x01      # U8 (read) current state
    REG_OUTPUT_PRR = 0x03     # U32 Hz (read) actual output rep rate
    REG_REL_POWER = 0x05      # U16 [0-4000] relative output power
    REG_FSM_TARGET = 0x30     # U8 target state [1,3,5,6]
    REG_INTERLOCK = 0x32      # H16 (>0 = reset)
    REG_SHUTTER = 0x34        # U8 [0=closed,1=open]
    REG_PRR_INDEX = 0x35      # U8 [0-12] rep-rate selector
    REG_FREQ_DIV = 0x36       # U32 [1-1000000] pulse picker
    REG_STATUS = 0x66         # U32 status bits

    FSM_OFF = 1               # CONFIRMED: observed standby/off state
    FSM_RUN = 6               # TODO confirm against manual (valid [1,3,5,6])
    POWER_FULL_SCALE = 4000   # raw value for 100 % (TODO confirm)

    # index -> Hz. Index 0 = 50 kHz is CONFIRMED from the unit; the rest follow
    # the stated allowed set (50,100,200..1000 kHz) and need confirmation.
    REP_RATE_INDEX_HZ = {0: 50e3, 1: 100e3, 2: 200e3, 3: 300e3, 4: 400e3,
                         5: 500e3, 6: 600e3, 7: 700e3, 8: 800e3, 9: 900e3,
                         10: 1000e3}

    def __init__(self, port: Optional[str] = None, *,
                 sdk_path: str = DEFAULT_SDK_PATH,
                 full_scale_energy_uj: float = 40.0):
        self.port = port
        self.address = 15
        self.sdk_path = sdk_path
        # Provisional pulse energy (uJ) at 100 % relative power; calibrate later.
        self.full_scale_energy_uj = full_scale_energy_uj
        self._nkt = None
        self._connected = False

    # --- low-level ----------------------------------------------------
    def _api(self):
        if self._nkt is None:
            self._nkt = _load_nkt(self.sdk_path)
        return self._nkt

    def _wr(self, fn_name: str, reg: int, value: int, *, what: str,
            raise_on_fail: bool = True) -> int:
        nkt = self._api()
        result = getattr(nkt, fn_name)(self.port, self.address, reg, value, -1)
        if result != _REG_SUCCESS:
            msg = "OrigamiXPS %s failed: %s" % (what, nkt.RegisterResultTypes(result))
            if raise_on_fail:
                raise RuntimeError(msg)
            log.error(msg)
        return result

    def _rd(self, fn_name: str, reg: int):
        nkt = self._api()
        result, value = getattr(nkt, fn_name)(self.port, self.address, reg, -1)
        return value if result == _REG_SUCCESS else None

    def find_modules(self) -> dict[int, int]:
        nkt = self._api()
        nkt.openPorts(nkt.getAllPorts(), 1, 0)
        found: dict[int, int] = {}
        for portname in [p for p in nkt.getOpenPorts().split(",") if p]:
            _r, dev_list = nkt.deviceGetAllTypesV2(portname)
            for addr, dtype in enumerate(dev_list):
                if dtype != 0 and (self.port is None or portname == self.port):
                    found[addr] = dtype
        return found

    # --- lifecycle ----------------------------------------------------
    def open(self) -> None:
        if self._connected:
            return
        # Passive connect: do NOT switch the interface mode or touch emission,
        # so a running laser can be handed to the vendor software untouched.
        nkt = self._api()
        modules = self.find_modules()
        open_ports = [p for p in nkt.getOpenPorts().split(",") if p]
        if self.port is None and open_ports:
            self.port = open_ports[0]
        if self.port is None:
            raise RuntimeError("OrigamiXPS: no NKT port found. Laser powered?")
        matches = [a for a, t in modules.items() if t == self.MODULE_TYPE]
        if matches:
            self.address = matches[0]
            log.info("OrigamiXPS found at address %d on %s." % (self.address, self.port))
        else:
            log.warn("OrigamiXPS: module type 0x95 not found among %s; using "
                     "address %d." % ({a: hex(t) for a, t in modules.items()},
                                      self.address))
        self._connected = True
        log.info("OrigamiXPS connected; state left unchanged.")

    def close(self) -> None:
        # Passive: leave emission as-is; just release the port.
        if self._connected:
            try:
                self._nkt.closePorts(self.port or "")
            except Exception as exc:  # pragma: no cover
                log.error("OrigamiXPS closePorts error: %s" % exc)
        self._connected = False
        log.info("OrigamiXPS closed (state left unchanged).")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- emission -----------------------------------------------------
    def enable(self) -> None:
        """Target the RUN state and open the internal shutter."""
        self._wr("registerWriteU8", self.REG_FSM_TARGET, self.FSM_RUN,
                 what="enable(FSM->RUN)")
        self._wr("registerWriteU8", self.REG_SHUTTER, 1, what="open shutter")
        log.info("OrigamiXPS: emission RUN requested (FSM=%d)." % self.FSM_RUN)

    def disable(self) -> None:
        """E-stop fast path: close the internal shutter AND target OFF.
        Both values are confirmed-safe; best-effort, retried, never raises."""
        for attempt in range(3):
            r1 = self._wr("registerWriteU8", self.REG_SHUTTER, 0,
                          what="close shutter", raise_on_fail=False)
            r2 = self._wr("registerWriteU8", self.REG_FSM_TARGET, self.FSM_OFF,
                          what="FSM->OFF", raise_on_fail=False)
            if r1 == _REG_SUCCESS and r2 == _REG_SUCCESS:
                log.info("OrigamiXPS: emission OFF (shutter closed, FSM=OFF).")
                return
            time.sleep(0.02)
        log.fatal("OrigamiXPS: FAILED to confirm emission OFF after retries!")

    @property
    def is_enabled(self) -> bool:
        status = self._rd("registerReadU32", self.REG_STATUS)
        return bool(status) and bool(status & 0x1)  # bit 0 = Emission On

    @property
    def emission_stage(self) -> str:
        state = self._rd("registerReadU8", self.REG_FSM_STATE)
        return {1: "off", 3: "standby", 5: "ready", 6: "emitting"}.get(
            state, "state %s" % state)

    # --- power --------------------------------------------------------
    def set_power_percent(self, percent: float) -> None:
        percent = max(0.0, min(100.0, percent))
        raw = int(round(percent / 100.0 * self.POWER_FULL_SCALE))
        self._wr("registerWriteU16", self.REG_REL_POWER, raw, what="set_power")
        log.info("OrigamiXPS: power %.1f %% (raw %d)." % (percent, raw))

    def read_power_percent(self) -> Optional[float]:
        raw = self._rd("registerReadU16", self.REG_REL_POWER)
        return None if raw is None else raw / self.POWER_FULL_SCALE * 100.0

    # --- pulse energy (uJ) via the relative power scale (provisional cal) --
    @property
    def max_pulse_energy_uj(self) -> Optional[float]:
        return self.full_scale_energy_uj

    def set_pulse_energy_uj(self, energy_uj: float) -> None:
        energy_uj = max(0.0, min(self.full_scale_energy_uj, energy_uj))
        self.set_power_percent(energy_uj / self.full_scale_energy_uj * 100.0)

    def read_pulse_energy_uj(self) -> Optional[float]:
        pct = self.read_power_percent()
        return None if pct is None else pct / 100.0 * self.full_scale_energy_uj

    # --- pulse picker (U32 frequency-division factor) -----------------
    def set_pulse_picker_ratio(self, ratio: int) -> None:
        if not 1 <= ratio <= 1_000_000:
            raise ValueError("Pulse-picker ratio must be in 1..1,000,000.")
        self._wr("registerWriteU32", self.REG_FREQ_DIV, int(ratio),
                 what="set_pulse_picker")
        log.info("OrigamiXPS: pulse-picker 1/%d." % ratio)

    def read_pulse_picker_ratio(self) -> Optional[int]:
        return self._rd("registerReadU32", self.REG_FREQ_DIV)

    # --- repetition rate (discrete index) -----------------------------
    def allowed_rep_rates_hz(self) -> Optional[tuple[float, ...]]:
        return tuple(self.REP_RATE_INDEX_HZ[i]
                     for i in sorted(self.REP_RATE_INDEX_HZ))

    def set_repetition_rate_hz(self, target_hz: float) -> float:
        # Pick the index whose mapped rate is nearest the requested value.
        index = min(self.REP_RATE_INDEX_HZ,
                    key=lambda i: abs(self.REP_RATE_INDEX_HZ[i] - target_hz))
        self._wr("registerWriteU8", self.REG_PRR_INDEX, index,
                 what="set_rep_rate_index")
        applied = self.REP_RATE_INDEX_HZ[index]
        log.info("OrigamiXPS: rep-rate index %d (%.0f kHz)." % (index, applied / 1e3))
        return applied

    def read_repetition_rate_hz(self) -> Optional[float]:
        # Actual output rep rate (Hz), read directly from the amplifier.
        raw = self._rd("registerReadU32", self.REG_OUTPUT_PRR)
        return None if raw is None else float(raw)

    # --- status -------------------------------------------------------
    def read_status_bits(self) -> dict[str, bool]:
        raw = self._rd("registerReadU32", self.REG_STATUS)
        if raw is None:
            return {}
        return {name: bool(raw & (1 << bit))
                for bit, name in _ORIGAMI_STATUS_BITS.items()}

    def reset_interlock(self) -> None:
        self._wr("registerWriteU16", self.REG_INTERLOCK, 1, what="reset_interlock")
        log.info("OrigamiXPS: interlock reset requested.")

    def get_status(self) -> str:
        if not self._connected:
            return "Disconnected"
        try:
            parts = [self.emission_stage]
            power = self.read_power_percent()
            if power is not None:
                parts.append("%.0f%%" % power)
            ratio = self.read_pulse_picker_ratio()
            if ratio:
                parts.append("PP 1/%d" % ratio)
            rate = self.read_repetition_rate_hz()
            if rate:
                parts.append("%.0f kHz" % (rate / 1e3))
            return ", ".join(parts)
        except Exception as exc:  # pragma: no cover
            return f"Error: {exc}"
