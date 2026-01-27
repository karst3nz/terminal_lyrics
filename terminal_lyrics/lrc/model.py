from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LyricEvent:
    t_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class LrcDocument:
    events: tuple[LyricEvent, ...]
    offset_ms: int = 0
    tags: dict[str, str] | None = None

