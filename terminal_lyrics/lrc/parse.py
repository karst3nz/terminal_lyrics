from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .model import LrcDocument, LyricEvent

_TS_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")  # [mm:ss] / [mm:ss.xx] / [mm:ss.xxx]
_OFFSET_RE = re.compile(r"^\[offset:([+-]?\d+)\]\s*$", re.IGNORECASE)
_TAG_RE = re.compile(r"^\[([a-zA-Z]{1,8}):(.*)\]\s*$")


class LrcParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LrcParseStats:
    lines_total: int
    events_total: int
    lines_with_timestamps: int
    lines_ignored: int


def _parse_ts_to_ms(m: int, s: int, frac: str | None) -> int:
    if not (0 <= s <= 59):
        raise LrcParseError(f"Invalid seconds: {s}")
    if frac is None:
        ms = 0
    else:
        # "2" -> 200ms, "23" -> 230ms, "234" -> 234ms
        ms = int(frac.ljust(3, "0")[:3])
    return (m * 60 + s) * 1000 + ms


def parse_lrc(text: str) -> LrcDocument:
    """
    Supported:
    - [mm:ss], [mm:ss.xx], [mm:ss.xxx]
    - multiple timestamps per line
    - [offset:+/-ms]
    - basic tags: [ar:], [ti:], [al:], ...

    Result is normalized:
    - events sorted by time then text
    - duplicate (t_ms, text) removed
    - negative times clamped to 0
    """
    offset_ms = 0
    tags: dict[str, str] = {}
    events: list[LyricEvent] = []

    total = 0
    lines_with_ts = 0
    ignored = 0

    for raw in text.splitlines():
        total += 1
        line = raw.rstrip("\n")
        if not line.strip():
            ignored += 1
            continue

        off = _OFFSET_RE.match(line)
        if off:
            try:
                offset_ms = int(off.group(1))
            except ValueError as e:
                raise LrcParseError("Invalid offset") from e
            continue

        tag = _TAG_RE.match(line)
        if tag and not _TS_RE.search(line):
            k = tag.group(1).strip().lower()
            v = tag.group(2).strip()
            if k and v:
                tags[k] = v
            continue

        ts = list(_TS_RE.finditer(line))
        if not ts:
            ignored += 1
            continue

        lines_with_ts += 1
        payload = line[ts[-1].end() :].lstrip()

        for m in ts:
            mm = int(m.group(1))
            ss = int(m.group(2))
            frac = m.group(3)
            t_ms = _parse_ts_to_ms(mm, ss, frac) + offset_ms
            if t_ms < 0:
                t_ms = 0
            events.append(LyricEvent(t_ms=t_ms, text=payload))

    events.sort(key=lambda e: (e.t_ms, e.text))
    dedup: list[LyricEvent] = []
    prev: tuple[int, str] | None = None
    for e in events:
        key = (e.t_ms, e.text)
        if key != prev:
            dedup.append(e)
            prev = key

    return LrcDocument(events=tuple(dedup), offset_ms=offset_ms, tags=tags)


def parse_lrc_with_stats(text: str) -> tuple[LrcDocument, LrcParseStats]:
    # thin wrapper for CLI diagnostics
    offset_ms = 0
    tags: dict[str, str] = {}
    events: list[LyricEvent] = []

    total = 0
    lines_with_ts = 0
    ignored = 0

    for raw in text.splitlines():
        total += 1
        line = raw.rstrip("\n")
        if not line.strip():
            ignored += 1
            continue

        off = _OFFSET_RE.match(line)
        if off:
            offset_ms = int(off.group(1))
            continue

        tag = _TAG_RE.match(line)
        if tag and not _TS_RE.search(line):
            k = tag.group(1).strip().lower()
            v = tag.group(2).strip()
            if k and v:
                tags[k] = v
            continue

        ts = list(_TS_RE.finditer(line))
        if not ts:
            ignored += 1
            continue

        lines_with_ts += 1
        payload = line[ts[-1].end() :].lstrip()
        for m in ts:
            t_ms = _parse_ts_to_ms(int(m.group(1)), int(m.group(2)), m.group(3)) + offset_ms
            if t_ms < 0:
                t_ms = 0
            events.append(LyricEvent(t_ms=t_ms, text=payload))

    events.sort(key=lambda e: (e.t_ms, e.text))
    dedup: list[LyricEvent] = []
    prev: tuple[int, str] | None = None
    for e in events:
        key = (e.t_ms, e.text)
        if key != prev:
            dedup.append(e)
            prev = key

    doc = LrcDocument(events=tuple(dedup), offset_ms=offset_ms, tags=tags)
    stats = LrcParseStats(
        lines_total=total,
        events_total=len(doc.events),
        lines_with_timestamps=lines_with_ts,
        lines_ignored=ignored,
    )
    return doc, stats

