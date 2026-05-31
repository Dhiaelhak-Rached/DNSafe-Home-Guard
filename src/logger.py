"""Shared logging utilities for HomeGuard."""

import logging
import os
from typing import Optional


def ensure_file_logging(log_dir: Optional[str] = None) -> None:
    """Add a FileHandler to the root logger if one is not already present."""
    if log_dir is None:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "homeguard.log")
    root = logging.getLogger()

    # Prevent duplicate handlers for the same file
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            if os.path.abspath(handler.baseFilename) == os.path.abspath(log_path):
                return

    handler = logging.FileHandler(log_path, encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    if root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
