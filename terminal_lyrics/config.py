from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    # Storage
    data_dir: Path
    cache_db_path: Path

    # Sources
    sources: tuple[str, ...]
    api_min_interval_s: float
    api_max_retries: int
    api_backoff_base_s: float

    # MPRIS
    preferred_player: str | None

    # Rendering
    refresh_hz: float
    context_lines: int  # lines above/below current
    use_alt_screen: bool


def load_config() -> AppConfig:
    # XDG base dir fallback
    xdg = os.getenv("XDG_CACHE_HOME")
    data_dir = Path(xdg) if xdg else Path.home() / ".cache"
    data_dir = data_dir / "terminal-lyrics"

    sources_env = os.getenv("TERMINAL_LYRICS_SOURCES", "lrclib")
    sources = tuple(s.strip() for s in sources_env.split(",") if s.strip())

    refresh_hz = float(os.getenv("TERMINAL_LYRICS_REFRESH_HZ", "30.0"))
    context_lines = int(os.getenv("TERMINAL_LYRICS_CONTEXT_LINES", "1"))
    use_alt_screen = os.getenv("TERMINAL_LYRICS_ALT_SCREEN", "1") not in ("0", "false", "False")

    return AppConfig(
        data_dir=data_dir,
        cache_db_path=data_dir / "cache.sqlite3",
        sources=sources,
        api_min_interval_s=float(os.getenv("TERMINAL_LYRICS_API_MIN_INTERVAL", "5.0")),
        api_max_retries=int(os.getenv("TERMINAL_LYRICS_API_MAX_RETRIES", "3")),
        api_backoff_base_s=float(os.getenv("TERMINAL_LYRICS_API_BACKOFF_BASE", "1.0")),
        preferred_player=os.getenv("TERMINAL_LYRICS_PLAYER") or None,
        refresh_hz=refresh_hz,
        context_lines=context_lines,
        use_alt_screen=use_alt_screen,
    )

