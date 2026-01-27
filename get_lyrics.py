"""
Backward-compatible helper.

Old code expected `get_lyrics()` to return a path to an .lrc file.
After refactor, lyrics are cached in SQLite; this helper fetches lyrics via
new service and writes a copy into XDG cache dir, returning the file path.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from terminal_lyrics.config import load_config
from terminal_lyrics.mpris.client import MprisClient
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable
from terminal_lyrics.sources.service import LyricsService
from terminal_lyrics.sources.types import TrackKey

logger = logging.getLogger(__name__)


_BAD_FS = re.compile(r"[\\/]+")


def _sanitize_filename(s: str) -> str:
    s2 = _BAD_FS.sub("_", s).strip()
    return s2 or "unknown"


def get_lyrics() -> str | None:
    cfg = load_config()
    svc = LyricsService(cfg)

    try:
        client = MprisClient.pick_player(preferred=cfg.preferred_player)
    except NoPlayersFound:
        return None

    try:
        ti = client.track_info()
    except PlayerUnavailable as e:
        logger.warning("MPRIS unavailable: %s", e)
        return None

    if not ti.artist or not ti.title:
        return None

    track = TrackKey(artist=ti.artist, title=ti.title, album=ti.album)
    res = svc.get_lyrics(track)
    if not res.has_lyrics or not res.lrc_text:
        return None

    out_dir = cfg.data_dir / "lyrics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_sanitize_filename(ti.artist)} - {_sanitize_filename(ti.title)}.lrc"
    out_path.write_text(res.lrc_text, encoding="utf-8")
    return str(out_path)
