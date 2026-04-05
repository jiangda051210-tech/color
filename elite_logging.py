"""
Structured JSON logging for SENIA Elite.

Usage:
    from elite_logging import get_logger
    logger = get_logger("elite_api")
    logger.info("analysis_complete", lot_id="L001", delta_e=1.23)
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge extra fields attached by StructuredLogger
        extra = getattr(record, "_structured_extra", None)
        if extra:
            payload.update(extra)
        if record.exc_info and record.exc_info[1]:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class StructuredLogger:
    """Thin wrapper around stdlib logging with structured extra fields."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    # --- convenience shortcuts with keyword extra fields ---

    def debug(self, msg: str, **extra: Any) -> None:
        self._log(logging.DEBUG, msg, extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._log(logging.INFO, msg, extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._log(logging.WARNING, msg, extra)

    def error(self, msg: str, exc_info: bool = False, **extra: Any) -> None:
        self._log(logging.ERROR, msg, extra, exc_info=exc_info)

    def critical(self, msg: str, exc_info: bool = False, **extra: Any) -> None:
        self._log(logging.CRITICAL, msg, extra, exc_info=exc_info)

    # --- internal ---

    def _log(self, level: int, msg: str, extra: dict[str, Any],
             exc_info: bool = False) -> None:
        if not self._logger.isEnabledFor(level):
            return
        record = self._logger.makeRecord(
            self._logger.name, level, "(structured)", 0, msg, (), None,
        )
        record._structured_extra = extra  # type: ignore[attr-defined]
        if exc_info:
            record.exc_info = sys.exc_info()
        self._logger.handle(record)


_CONFIGURED = False


def setup_logging(
    level: str = "info",
    log_file: Path | None = None,
) -> None:
    """Configure root JSON logging. Safe to call multiple times (idempotent)."""
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED:
        return
    _CONFIGURED = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = _JsonFormatter()

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        from logging.handlers import RotatingFileHandler
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            str(log_file), encoding="utf-8",
            maxBytes=100 * 1024 * 1024,  # 100MB per file
            backupCount=10,
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)


def get_logger(name: str) -> StructuredLogger:
    """Return a structured logger with the given name."""
    return StructuredLogger(logging.getLogger(name))
