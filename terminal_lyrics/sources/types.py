from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrackKey:
    artist: str
    title: str
    album: str = ""

    @property
    def display(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.artist or "Unknown track"


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Результат поиска лирики."""
    id: int | None
    track_name: str
    artist_name: str
    album_name: str
    duration: int | None
    instrumental: bool
    has_synced_lyrics: bool
    has_plain_lyrics: bool
    synced_lyrics_text: str | None = None  # Текст синхронизированных лириков из результатов поиска
    plain_lyrics_text: str | None = None  # Текст обычных лириков из результатов поиска

