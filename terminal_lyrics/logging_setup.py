from __future__ import annotations

import logging
import os
from pathlib import Path


def setup_logging(debug: bool, log_to_file: bool = False) -> None:
    level = logging.DEBUG if debug else logging.INFO
    # Allow env override for e.g. systemd service runs
    level_name = os.getenv("TERMINAL_LYRICS_LOG_LEVEL")
    if level_name:
        try:
            level = getattr(logging, level_name.upper())
        except AttributeError:
            pass

    # Setup handlers
    handlers = []

    # Console handler (only if not logging to file, or if debug mode)
    if not log_to_file or debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handlers.append(console_handler)

    # File handler
    if log_to_file or os.getenv("TERMINAL_LYRICS_LOG_FILE"):
        log_dir = Path.home() / ".cache" / "terminal-lyrics"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "terminal-lyrics.log"

        file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if log_to_file:
        logging.info(f"Logging to file: {log_dir / 'terminal-lyrics.log'}")
