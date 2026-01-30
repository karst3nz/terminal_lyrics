from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path


def _config_dir() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "terminal-lyrics"
    return Path.home() / ".config" / "terminal-lyrics"


def _config_file() -> Path:
    return _config_dir() / "config.json"


@dataclass(frozen=True)
class AppConfig:
    # Storage
    data_dir: Path
    cache_db_path: Path
    config_dir: Path

    # Locale
    lang: str

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

    config_dir = _config_dir()
    lang = _load_lang(config_dir)

    return AppConfig(
        data_dir=data_dir,
        cache_db_path=data_dir / "cache.sqlite3",
        config_dir=config_dir,
        lang=lang,
        sources=sources,
        api_min_interval_s=float(os.getenv("TERMINAL_LYRICS_API_MIN_INTERVAL", "5.0")),
        api_max_retries=int(os.getenv("TERMINAL_LYRICS_API_MAX_RETRIES", "3")),
        api_backoff_base_s=float(os.getenv("TERMINAL_LYRICS_API_BACKOFF_BASE", "1.0")),
        preferred_player=os.getenv("TERMINAL_LYRICS_PLAYER") or None,
        refresh_hz=refresh_hz,
        context_lines=context_lines,
        use_alt_screen=use_alt_screen,
    )


def _load_lang(config_dir: Path) -> str:
    # Priority: config.json → TERMINAL_LYRICS_LANG → "EN"
    cfg_path = config_dir / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw = (data.get("lang") or "en").upper()
            if raw in ("RU", "EN"):
                return raw
        except Exception:
            pass
    env_lang = os.getenv("TERMINAL_LYRICS_LANG")
    if env_lang and env_lang.upper() in ("RU", "EN"):
        return env_lang.upper()
    return "EN"


def save_config_lang(lang: str) -> None:
    cfg_path = _config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["lang"] = lang.upper()
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

