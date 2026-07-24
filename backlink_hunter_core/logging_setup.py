"""Rotating log configuration."""

from __future__ import annotations

import logging

import logging.handlers

from pathlib import Path

from typing import Optional

_CONFIGURED = False

def setup_logging(log_dir: str = "logs", level: str = "INFO",

                  max_bytes: int = 5 * 1024 * 1024, backups: int = 5) -> logging.Logger:

    global _CONFIGURED

    logger = logging.getLogger("backlink_hunter")

    if _CONFIGURED:

        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    logger.propagate = False

    fmt = logging.Formatter(

        "%(asctime)s %(levelname)-7s %(name)s [%(threadName)s] %(message)s"

    )

    stream = logging.StreamHandler()

    stream.setFormatter(fmt)

    logger.addHandler(stream)

    try:

        Path(log_dir).mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(

            Path(log_dir) / "backlink_hunter.log",

            maxBytes=max_bytes, backupCount=backups, encoding="utf-8",

        )

        file_handler.setFormatter(fmt)

        logger.addHandler(file_handler)

    except OSError:

        logger.warning("Could not create log directory %s; console logging only", log_dir)

    _CONFIGURED = True

    return logger

def get_logger(name: Optional[str] = None) -> logging.Logger:

    base = logging.getLogger("backlink_hunter")

    if name:

        return base.getChild(name)

    return base
