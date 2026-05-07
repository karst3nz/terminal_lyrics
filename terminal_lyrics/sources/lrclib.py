from __future__ import annotations

import asyncio
import logging
import time
from typing import List

import httpx

from .base import FetchResult, LyricsSource
from .types import SearchResult, TrackKey

logger = logging.getLogger(__name__)


class LrcLibSource(LyricsSource):
    name = "lrclib"

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
            
            params = {
                "artist_name": track.artist,
                "track_name": track.title,
                "album_name": track.album,
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self._last_call_time = time.time()
                        r = await client.get("https://lrclib.net/api/get", params=params)
                        if r.status_code == 404:
                            return FetchResult(None, True, self.name)
                        r.raise_for_status()
                        data = r.json()
                        lrc = data.get("syncedLyrics")
                        if not lrc:
                            return FetchResult(None, True, self.name)
                        return FetchResult(str(lrc).rstrip() + "\n", False, self.name)
                    except httpx.RequestError as e:
                        logger.warning("lrclib error (attempt %s/%s): %s", attempt, self.max_retries, e)
                        if attempt == self.max_retries:
                            return FetchResult(None, False, self.name)
                        await asyncio.sleep(self.backoff_base_s)
                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            return FetchResult(None, True, self.name)
                        logger.warning("lrclib error (attempt %s/%s): %s", attempt, self.max_retries, e)
                        if attempt == self.max_retries:
                            return FetchResult(None, False, self.name)
                        await asyncio.sleep(self.backoff_base_s)

            return FetchResult(None, False, self.name)

    async def search(
        self,
        *,
        q: str | None = None,
        track_name: str | None = None,
        artist_name: str | None = None,
        album_name: str | None = None,
    ) -> List[SearchResult]:
        """
        Поиск лирики через lrclib API /api/search.

        Требуется хотя бы один из параметров: q или track_name.
        """
        if not q and not track_name:
            raise ValueError("At least one of 'q' or 'track_name' must be provided")

        params: dict[str, str] = {}
        if q:
            params["q"] = q
        if track_name:
            params["track_name"] = track_name
        if artist_name:
            params["artist_name"] = artist_name
        if album_name:
            params["album_name"] = album_name

        async with self._http_lock:
            try:
                self._last_call_time = time.time()
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get("https://lrclib.net/api/search", params=params)
                    r.raise_for_status()
                    data = r.json()

                results = []
                for item in data:
                    synced = item.get("syncedLyrics")
                    plain = item.get("plainLyrics")
                    synced_text = None
                    plain_text = None
                    if synced and synced is not None:
                        synced_text = str(synced).rstrip() + "\n"
                    if plain and plain is not None:
                        plain_text = str(plain).rstrip() + "\n"
                    results.append(
                        SearchResult(
                            id=item.get("id"),
                            track_name=item.get("trackName", ""),
                            artist_name=item.get("artistName", ""),
                            album_name=item.get("albumName", ""),
                            duration=item.get("duration"),
                            instrumental=item.get("instrumental", False),
                            has_synced_lyrics=bool(synced) and synced is not None,
                            has_plain_lyrics=bool(plain) and plain is not None,
                            synced_lyrics_text=synced_text,
                            plain_lyrics_text=plain_text,
                        )
                    )
                return results
            except httpx.RequestError as e:
                logger.error("lrclib search error: %s", e)
                return []
            except httpx.HTTPStatusError as e:
                logger.error("lrclib search error: %s", e)
                return []
