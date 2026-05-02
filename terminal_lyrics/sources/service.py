from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from terminal_lyrics.cache.sqlite import CacheKey, LyricsCache
from terminal_lyrics.config import AppConfig

from .base import LyricsSource
from .local_ingest import LocalLyricsStore
from .lrclib import LrcLibSource
from .lyrics_ovh import LyricsOvhSource
from .types import SearchResult, TrackKey

logger = logging.getLogger(__name__)

# Leading [tag] blocks on a line (LRC timestamps, metadata, etc.)
_LRC_LEADING_TAG = re.compile(r"^\[[^\]]*\]\s*")


def _lrc_line_after_tags(line: str) -> str:
    """Strip leading «[…]» segments so «[00:00.00] ...» yields «...»."""
    s = line.strip()
    while True:
        m = _LRC_LEADING_TAG.match(s)
        if not m:
            break
        s = s[m.end() :].lstrip()
    return s.strip()


def _is_ellipsis_only_content(s: str) -> bool:
    """True if the line is empty or only ellipsis / dots (Yandex placeholders)."""
    if not s:
        return True
    for ch in s:
        if ch not in ".…":
            return False
    return True


def _line_has_ellipsis_placeholder(line: str) -> bool:
    """True if the line contains a literal «...» or Unicode ellipsis (Yandex-style)."""
    return "..." in line or "\u2026" in line


def _needs_lrclib_fallback(text: str | None) -> bool:
    """
    True if lyrics should be replaced via LRCLib: empty, whole-text ellipsis-only,
    a single non-empty line that contains «...»/…, or several lines that are all
    placeholder-only after LRC tags (e.g. many «[00:00.00] ...» from Yandex).
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    if stripped == "..." or stripped == "\u2026":
        return True
    non_empty_lines = [ln for ln in text.splitlines() if ln.strip()]
    if not non_empty_lines:
        return True
    if len(non_empty_lines) == 1:
        return _line_has_ellipsis_placeholder(non_empty_lines[0])
    return all(_is_ellipsis_only_content(_lrc_line_after_tags(ln)) for ln in non_empty_lines)


@dataclass(frozen=True, slots=True)
class LyricsResponse:
    lrc_text: str | None
    source: str | None
    has_lyrics: bool


class LyricsService:
    def __init__(
        self,
        cfg: AppConfig,
        *,
        local_ingest_store: LocalLyricsStore | None = None,
    ):
        self.cfg = cfg
        self.cache = LyricsCache(cfg.cache_db_path)
        self.sources = self._build_sources(cfg)
        self._ingest_store: LocalLyricsStore | None = (
            local_ingest_store if cfg.ingest_enabled else None
        )

    @staticmethod
    def _build_sources(cfg: AppConfig) -> list[LyricsSource]:
        out: list[LyricsSource] = []
        for s in cfg.sources:
            name = s.strip().lower()
            if name == "lrclib":
                out.append(
                    LrcLibSource(
                        min_interval_s=cfg.api_min_interval_s,
                        max_retries=cfg.api_max_retries,
                        backoff_base_s=cfg.api_backoff_base_s,
                    )
                )
            elif name in ("lyrics_ovh", "lyrics.ovh", "ovh"):
                out.append(
                    LyricsOvhSource(
                        min_interval_s=cfg.api_min_interval_s,
                        max_retries=cfg.api_max_retries,
                        backoff_base_s=cfg.api_backoff_base_s,
                    )
                )
            else:
                logger.debug("Unknown source '%s' in config, skipping", s)
        return out

    async def _postcheck_placeholder_to_lrclib(
        self,
        track: TrackKey,
        key: CacheKey,
        lrc_text: str | None,
        source: str | None,
    ) -> LyricsResponse:
        """
        If lyrics are trivial (empty, placeholder lines, or one line with «...»/…), try LRCLib.
        Otherwise return unchanged.
        """
        if lrc_text is None:
            return LyricsResponse(lrc_text=None, source=source, has_lyrics=False)
        if not _needs_lrclib_fallback(lrc_text):
            return LyricsResponse(lrc_text=lrc_text, source=source, has_lyrics=True)

        logger.debug(
            "Post-check: trivial lyrics (placeholder/…), LRCLib search for %s", track.display
        )
        resolved = await self._lrclib_best_lyrics_from_search(track)
        if resolved:
            await self.cache.set(key, has_lyrics=True, lrc_text=resolved, source="lrclib_search")
            return LyricsResponse(lrc_text=resolved, source="lrclib_search", has_lyrics=True)
        return LyricsResponse(lrc_text=lrc_text, source=source, has_lyrics=True)

    async def _lrclib_best_lyrics_from_search(self, track: TrackKey) -> str | None:
        """LRCLib search + best match; returns text or None (rejects trivial lyrics)."""
        search_results = await self._auto_search_fallback(track)
        if not search_results:
            return None
        best_match = self._find_best_match(track, search_results)
        if not best_match:
            return None
        lrc_text = best_match.synced_lyrics_text
        if not lrc_text and best_match.has_synced_lyrics:
            lrc_text = await self._fetch_lyrics_by_search_result(best_match)
        if not lrc_text and best_match.has_plain_lyrics:
            lrc_text = best_match.plain_lyrics_text
        if lrc_text and not _needs_lrclib_fallback(lrc_text):
            return lrc_text
        return None

    async def get_lyrics(self, track: TrackKey) -> LyricsResponse:
        key = CacheKey(artist=track.artist, title=track.title, album=track.album)
        # Then check cache
        cached_text, cached_has, cached_source = await self.cache.get(key)
        if cached_has is True and cached_text is not None:
            if _needs_lrclib_fallback(cached_text):
                logger.debug(
                    "Кэш: trivial lyrics (placeholder/…), LRCLib search для %s", track.display
                )
                resolved = await self._lrclib_best_lyrics_from_search(track)
                if resolved:
                    await self.cache.set(
                        key, has_lyrics=True, lrc_text=resolved, source="lrclib_search"
                    )
                    return LyricsResponse(
                        lrc_text=resolved, source="lrclib_search", has_lyrics=True
                    )
                # LRCLib не помог — продолжаем источники / поиск ниже
            else:
                return LyricsResponse(
                    lrc_text=cached_text,
                    source=cached_source or "cache",
                    has_lyrics=True,
                )
        # При has_lyrics=False в кэше — всё равно проверяем источники (лирики могли появиться)
        if cached_has is False:
            logger.debug("Кэш: has_lyrics=0 для %s, проверяем источники", track.display)

        # Fetch sources in order; if any says "definitive_not_found", we still try others
        # (because some sources may have synced lyrics while others don't).
        for src in self.sources:
            res = await src.fetch(track)
            if _needs_lrclib_fallback(res.lrc_text):
                    return await self._postcheck_placeholder_to_lrclib(
                        track, key, res.lrc_text, res.source
                    )  
            elif res.lrc_text and not _needs_lrclib_fallback(res.lrc_text):
                await self.cache.set(key, has_lyrics=True, lrc_text=res.lrc_text, source=res.source)
                return LyricsResponse(
                    lrc_text=res.lrc_text, source=res.source, has_lyrics=True
                )
          
        # Then check ingest for real-time lyrics (prioritize over cache)
        if self._ingest_store is not None:
            ingest_key = CacheKey(artist=track.artist, title=track.title, album=track.album or "")
            logger.debug("Checking ingest for %s", track.display)
            ingested = await self._ingest_store.wait_for_lyrics(
                ingest_key, self.cfg.ingest_wait_timeout_s
            )
            if ingested:
                logger.debug("Using ingested lyrics for %s", track.display)
                if _needs_lrclib_fallback(ingested):
                    return await self._postcheck_placeholder_to_lrclib(
                        track, key, ingested, "local_ingest"
                    )
                await self.cache.set(key, has_lyrics=True, lrc_text=ingested, source="local_ingest")
                return LyricsResponse(
                    lrc_text=ingested, source="local_ingest", has_lyrics=True
                )

        # Если точного совпадения нет, пробуем автоматический поиск через search API
        # (только если есть LrcLibSource)
        lrclib_source = next((src for src in self.sources if isinstance(src, LrcLibSource)), None)
        if lrclib_source:
            logger.debug("Точное совпадение не найдено, пробуем поиск для %s", track.display)
            lrc_text = await self._lrclib_best_lyrics_from_search(track)
            if lrc_text:
                await self.cache.set(
                    key, has_lyrics=True, lrc_text=lrc_text, source="lrclib_search"
                )
                return LyricsResponse(
                    lrc_text=lrc_text, source="lrclib_search", has_lyrics=True
                )

        # negative cache to avoid hammering
        await self.cache.set(key, has_lyrics=False, lrc_text=None, source=None)
        return LyricsResponse(lrc_text=None, source=None, has_lyrics=False)

    async def _auto_search_fallback(self, track: TrackKey) -> list[SearchResult]:
        """Автоматический поиск при отсутствии точного совпадения."""
        query = f"{track.artist} {track.title}".strip()
        if not query:
            return []

        results = await self.search(q=query, track_name=track.title, artist_name=track.artist)

        # Если нет результатов и исполнителей несколько (через ",") — ищем по каждому
        if not results and "," in (track.artist or ""):
            artists = [a.strip() for a in track.artist.split(",") if a.strip()]
            seen_ids: set[int | None] = set()
            for artist in artists:
                sub_query = f"{artist} {track.title}".strip()
                sub_results = await self.search(
                    q=sub_query, track_name=track.title, artist_name=artist
                )
                for r in sub_results:
                    if r.id not in seen_ids:
                        seen_ids.add(r.id)
                        results.append(r)

        return results

    def _find_best_match(self, track: TrackKey, results: list[SearchResult]) -> SearchResult | None:
        """Находит лучший результат поиска по совпадению artist/title."""
        if not results:
            return None

        track_title_lower = (track.title or "").lower().strip()
        track_artist_lower = (track.artist or "").lower().strip()
        track_artists = [
            a.strip().lower() for a in (track.artist or "").split(",") if a.strip()
        ] or ([track_artist_lower] if track_artist_lower else [])

        best_score = -1
        best_result: SearchResult | None = None

        for r in results:
            score = 0
            r_artist_lower = (r.artist_name or "").lower().strip()
            r_title_lower = (r.track_name or "").lower().strip()

            title_exact = r_title_lower == track_title_lower
            title_partial = bool(
                track_title_lower
                and r_title_lower
                and (track_title_lower in r_title_lower or r_title_lower in track_title_lower)
            )

            artist_exact_full = r_artist_lower == track_artist_lower
            artist_one_of = r_artist_lower in track_artists
            artist_partial = (
                r_artist_lower in track_artist_lower
                or track_artist_lower in r_artist_lower
                or any(r_artist_lower in ta or ta in r_artist_lower for ta in track_artists)
            )

            if title_exact:
                score += 50
            elif title_partial:
                score += 15

            if artist_exact_full:
                score += 50
            elif artist_one_of:
                score += 45
            elif artist_partial:
                score += 20

            if r.has_synced_lyrics:
                score += 5
            elif r.has_plain_lyrics:
                score += 2

            if score > best_score:
                best_score = score
                best_result = r

        return best_result if best_score > 0 else None

    async def _fetch_lyrics_by_search_result(self, result: SearchResult) -> str | None:
        """Получает syncedLyrics для результата поиска через обычный fetch."""
        if not result.has_synced_lyrics:
            return None

        # Используем найденные artist/title для обычного fetch
        track = TrackKey(
            artist=result.artist_name, title=result.track_name, album=result.album_name
        )
        for src in self.sources:
            if isinstance(src, LrcLibSource):
                fetch_res = await src.fetch(track)
                if fetch_res.lrc_text and not _needs_lrclib_fallback(fetch_res.lrc_text):
                    return fetch_res.lrc_text
        return None

    async def search(
        self,
        *,
        q: str | None = None,
        track_name: str | None = None,
        artist_name: str | None = None,
        album_name: str | None = None,
    ) -> list[SearchResult]:
        """
        Поиск лирики через доступные источники.
        Сейчас поддерживается только lrclib.
        """
        results: list[SearchResult] = []
        for src in self.sources:
            if isinstance(src, LrcLibSource):
                results.extend(
                    await src.search(
                        q=q,
                        track_name=track_name,
                        artist_name=artist_name,
                        album_name=album_name,
                    )
                )
                # Пока используем только первый источник с поддержкой поиска
                break
        return results
