from __future__ import annotations

import logging
import os


def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    # Allow env override for e.g. systemd service runs
    level_name = os.getenv("TERMINAL_LYRICS_LOG_LEVEL")
    if level_name:
        try:
            level = getattr(logging, level_name.upper())
        except AttributeError:
            pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

