from __future__ import annotations

import logging
import time

import requests

from .base import FetchResult, LyricsSource
from .types import TrackKey

logger = logging.getLogger(__name__)


class LyricsOvhSource(LyricsSource):
    name = "lyrics_ovh"

    def __init__(self, *, min_interval_s: float, max_retries: int, backoff_base_s: float):
        self.min_interval_s = min_interval_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._last_call_time = 0.0

    def fetch(self, track: TrackKey) -> FetchResult:
        now = time.time()
        if self._last_call_time and now - self._last_call_time < self.min_interval_s:
            return FetchResult(lrc_text=None, definitive_not_found=False, source=self.name)

        url = f"https://api.lyrics.ovh/v1/{requests.utils.quote(track.artist)}/{requests.utils.quote(track.title)}"

        for attempt in range(1, self.max_retries + 1):
            try:
                self._last_call_time = time.time()
                r = requests.get(url, timeout=10)
                if r.status_code == 404:
                    return FetchResult(None, True, self.name)
                r.raise_for_status()
                data = r.json()
                lyrics = data.get("lyrics")
                if not lyrics:
                    return FetchResult(None, True, self.name)
                # This source is plain lyrics (no timing). Keep text as-is.
                return FetchResult(str(lyrics).rstrip() + "\n", False, self.name)
            except requests.RequestException as e:
                logger.warning("lyrics.ovh error (attempt %s/%s): %s", attempt, self.max_retries, e)
                if attempt == self.max_retries:
                    return FetchResult(None, False, self.name)
                time.sleep(self.backoff_base_s * attempt)

        return FetchResult(None, False, self.name)

