from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import quote

import httpx

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
        self._http_lock = asyncio.Lock()

    async def fetch(self, track: TrackKey) -> FetchResult:
        async with self._http_lock:
            now = time.time()
            if self._last_call_time and now - self._last_call_time < self.min_interval_s:
                return FetchResult(lrc_text=None, definitive_not_found=False, source=self.name)

            url = f"https://api.lyrics.ovh/v1/{quote(track.artist)}/{quote(track.title)}"

            async with httpx.AsyncClient(timeout=10.0) as client:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._last_call_time = time.time()
                        r = await client.get(url)
                        if r.status_code == 404:
                            return FetchResult(None, True, self.name)
                        r.raise_for_status()
                        data = r.json()
                        lyrics = data.get("lyrics")
                        if not lyrics:
                            return FetchResult(None, True, self.name)
                        return FetchResult(str(lyrics).rstrip() + "\n", False, self.name)
                    except httpx.RequestError as e:
                        logger.warning(
                            "lyrics.ovh error (attempt %s/%s): %s", attempt, self.max_retries, e
                        )
                        if attempt == self.max_retries:
                            return FetchResult(None, False, self.name)
                        await asyncio.sleep(self.backoff_base_s * attempt)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            return FetchResult(None, True, self.name)
                        logger.warning(
                            "lyrics.ovh error (attempt %s/%s): %s", attempt, self.max_retries, e
                        )
                        if attempt == self.max_retries:
                            return FetchResult(None, False, self.name)
                        await asyncio.sleep(self.backoff_base_s * attempt)

            return FetchResult(None, False, self.name)
