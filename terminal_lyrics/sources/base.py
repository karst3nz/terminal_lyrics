from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .types import TrackKey


@dataclass(frozen=True, slots=True)
class FetchResult:
    lrc_text: str | None
    definitive_not_found: bool
    source: str


class LyricsSource(ABC):
    name: str

    @abstractmethod
    async def fetch(self, track: TrackKey) -> FetchResult:
        raise NotImplementedError
