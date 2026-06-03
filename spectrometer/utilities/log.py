"""Lightweight logging shim.

Preserves the call surface of the original project logger
(``log.register/debug/trace/info/warn/error/fatal/finish`` accepting
multiple positional args) but is built on the Python standard ``logging``
module, with no third-party dependencies and no fragile config-file parsing.

Drivers and controllers call e.g. ``log.info('moving', steps)`` -- the
positional arguments are stringified and space-joined, matching the old
behaviour, so existing driver code works unchanged.
"""
from __future__ import annotations

import logging
import os
import time

_LOGGER_NAME = "spectrometer"
_logger = logging.getLogger(_LOGGER_NAME)
_file_handler: logging.FileHandler | None = None

# Map the old TRACE level (finer than DEBUG) onto a custom level.
TRACE_LEVEL = 5
logging.addLevelName(TRACE_LEVEL, "TRACE")


def register(level: int = logging.INFO, *, logdir: str = "logs",
             to_file: bool = True) -> None:
    """Initialise the logger. Safe to call more than once."""
    global _file_handler

    _logger.setLevel(TRACE_LEVEL)  # let handlers do the filtering
    if not _logger.handlers:
        stream = logging.StreamHandler()
        stream.setLevel(level)
        stream.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"))
        _logger.addHandler(stream)

    if to_file and _file_handler is None:
        try:
            os.makedirs(logdir, exist_ok=True)
            logname = time.strftime("%Y%m%dT%H%M%S")
            _file_handler = logging.FileHandler(
                os.path.join(logdir, f"{logname}.txt"), encoding="utf-8")
            _file_handler.setLevel(TRACE_LEVEL)
            _file_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(filename)s:%(lineno)d] %(message)s"))
            _logger.addHandler(_file_handler)
        except OSError as exc:  # pragma: no cover - filesystem dependent
            _logger.error("Failed to open log file: %s", exc)


def _join(args: tuple) -> str:
    return " ".join(str(a) for a in args)


def debug(*args, **_kwargs) -> None:
    _logger.debug(_join(args), stacklevel=2)


def trace(*args, **_kwargs) -> None:
    _logger.log(TRACE_LEVEL, _join(args), stacklevel=2)


def info(*args, **_kwargs) -> None:
    _logger.info(_join(args), stacklevel=2)


def warn(*args, **_kwargs) -> None:
    _logger.warning(_join(args), stacklevel=2)


# alias for callers expecting the stdlib spelling
warning = warn


def error(*args, **_kwargs) -> None:
    _logger.error(_join(args), stacklevel=2)


def fatal(*args, **_kwargs) -> None:
    _logger.critical(_join(args), stacklevel=2)


def finish() -> None:
    info("Logger closing.")
    for handler in list(_logger.handlers):
        handler.flush()
