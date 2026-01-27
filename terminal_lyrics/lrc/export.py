from __future__ import annotations

import json
from datetime import timedelta

from .model import LrcDocument


def export_json(doc: LrcDocument) -> str:
    return json.dumps(
        {
            "offset_ms": doc.offset_ms,
            "tags": doc.tags or {},
            "events": [{"t_ms": e.t_ms, "text": e.text} for e in doc.events],
        },
        ensure_ascii=False,
        indent=2,
    )


def _fmt_lrc_time(ms: int) -> str:
    m, rem = divmod(ms, 60_000)
    s, ms2 = divmod(rem, 1_000)
    # keep 2 decimals for compatibility
    return f"{m:02d}:{s:02d}.{ms2 // 10:02d}"


def export_lrc(doc: LrcDocument, include_tags: bool = True, include_offset: bool = True) -> str:
    out: list[str] = []
    if include_tags and doc.tags:
        for k in sorted(doc.tags.keys()):
            out.append(f"[{k}:{doc.tags[k]}]")
    if include_offset and doc.offset_ms:
        out.append(f"[offset:{doc.offset_ms}]")

    for e in doc.events:
        out.append(f"[{_fmt_lrc_time(e.t_ms)}]{e.text}")
    return "\n".join(out) + ("\n" if out else "")


def _fmt_srt_time(ms: int) -> str:
    # HH:MM:SS,mmm
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms2 = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms2:03d}"


def export_srt(doc: LrcDocument, last_line_duration_ms: int = 2000) -> str:
    """
    End time is next start time, last line ends at +last_line_duration_ms.
    """
    ev = doc.events
    if not ev:
        return ""
    out: list[str] = []
    for i, e in enumerate(ev, start=1):
        start = e.t_ms
        if i < len(ev):
            end = max(ev[i].t_ms, start + 1)
        else:
            end = start + last_line_duration_ms
        out.append(str(i))
        out.append(f"{_fmt_srt_time(start)} --> {_fmt_srt_time(end)}")
        out.append(e.text or "")
        out.append("")
    return "\n".join(out)

