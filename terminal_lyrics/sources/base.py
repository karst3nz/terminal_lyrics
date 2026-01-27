from __future__ import annotations

from dataclasses import dataclass

from .types import TrackKey


@dataclass(frozen=True, slots=True)
class FetchResult:
    lrc_text: str | None
    definitive_not_found: bool
    source: str


class LyricsSource:
    name: str

    def fetch(self, track: TrackKey) -> FetchResult:
        raise NotImplementedError

