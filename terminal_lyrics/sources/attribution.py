"""Lyrics source line for the footer (Источник: …)."""

from __future__ import annotations

from terminal_lyrics.i18n import t


def format_lyrics_source_footer(source_key: str | None) -> str | None:
    """Return a single localized line like «Источник: LRCLIB», or None if unknown."""
    if not source_key:
        return None
    label_key = f"source_{source_key}"
    label = t(label_key)
    if label == label_key:
        label = source_key.replace("_", " ")
    return t("lyrics_source_footer", sources=label)
