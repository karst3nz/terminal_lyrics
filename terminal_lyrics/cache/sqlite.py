from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CacheKey:
    artist: str
    title: str
    album: str


class LyricsCache:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS lyrics_cache (
                    artist TEXT NOT NULL,
                    title  TEXT NOT NULL,
                    album  TEXT NOT NULL DEFAULT '',
                    has_lyrics INTEGER NOT NULL,
                    source TEXT,
                    lrc_text TEXT,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (artist, title, album)
                );
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_lyrics_cache_updated_at ON lyrics_cache(updated_at);"
            )

    def get(self, key: CacheKey) -> tuple[str | None, bool | None]:
        """
        Returns (lrc_text, has_lyrics) or (None, None) if no entry.
        """
        with self._connect() as con:
            row = con.execute(
                "SELECT has_lyrics, lrc_text FROM lyrics_cache WHERE artist=? AND title=? AND album=?",
                (key.artist, key.title, key.album),
            ).fetchone()
            if row is None:
                return None, None
            has = bool(row["has_lyrics"])
            return (row["lrc_text"] if has else None), has

    def set(self, key: CacheKey, *, has_lyrics: bool, lrc_text: str | None, source: str | None) -> None:
        now = int(time.time())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO lyrics_cache(artist, title, album, has_lyrics, source, lrc_text, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artist, title, album) DO UPDATE SET
                    has_lyrics=excluded.has_lyrics,
                    source=excluded.source,
                    lrc_text=excluded.lrc_text,
                    updated_at=excluded.updated_at
                """,
                (key.artist, key.title, key.album, int(has_lyrics), source, lrc_text, now),
            )

    def clear(self) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM lyrics_cache")

