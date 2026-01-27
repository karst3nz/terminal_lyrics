from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from terminal_lyrics.lrc.model import LyricEvent


@dataclass(slots=True)
class LineTracker:
    """
    Efficient lookup: O(log n) via bisect + update only on change.
    """

    t_ms: list[int]
    texts: list[str]
    last_idx: int = -1

    @classmethod
    def from_events(cls, events: tuple[LyricEvent, ...]) -> "LineTracker":
        t_ms = [e.t_ms for e in events]
        texts = [e.text for e in events]
        return cls(t_ms=t_ms, texts=texts)

    def current_index(self, now_ms: int) -> int:
        i = bisect_right(self.t_ms, now_ms) - 1
        return i if i >= 0 else -1

    def changed_index(self, now_ms: int) -> int | None:
        i = self.current_index(now_ms)
        if i != self.last_idx:
            self.last_idx = i
            return i
        return None

