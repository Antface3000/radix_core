"""Lightweight logging setup for Radix Core."""

from __future__ import annotations

import logging
import os
import sys

LOG = logging.getLogger("radix")


def setup_logging(verbose: bool = False) -> None:
    """Configure root logging once at app startup."""
    if LOG.handlers:
        return
    env_debug = os.environ.get("RADIX_DEBUG", "").strip().lower() in ("1", "true", "yes")
    level = logging.DEBUG if (verbose or env_debug) else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    LOG.setLevel(level)
    LOG.debug("Logging level=%s", logging.getLevelName(level))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"radix.{name}")
