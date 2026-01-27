from __future__ import annotations

import logging
from dataclasses import dataclass

from terminal_lyrics.cache.sqlite import CacheKey, LyricsCache
from terminal_lyrics.config import AppConfig

from .base import LyricsSource
from .lrclib import LrcLibSource
from .lyrics_ovh import LyricsOvhSource
from .types import SearchResult, TrackKey

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LyricsResponse:
    lrc_text: str | None
    source: str | None
    has_lyrics: bool


class LyricsService:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.cache = LyricsCache(cfg.cache_db_path)
        self.sources = self._build_sources(cfg)

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
                logger.info("Unknown source '%s' in config, skipping", s)
        return out

    def get_lyrics(self, track: TrackKey) -> LyricsResponse:
        key = CacheKey(artist=track.artist, title=track.title, album=track.album)
        cached_text, cached_has = self.cache.get(key)
        if cached_has is True and cached_text is not None:
            return LyricsResponse(lrc_text=cached_text, source="cache", has_lyrics=True)
        if cached_has is False:
            return LyricsResponse(lrc_text=None, source="cache", has_lyrics=False)

        # Fetch sources in order; if any says "definitive_not_found", we still try others
        # (because some sources may have synced lyrics while others don't).
        for src in self.sources:
            res = src.fetch(track)
            if res.lrc_text:
                self.cache.set(key, has_lyrics=True, lrc_text=res.lrc_text, source=res.source)
                return LyricsResponse(lrc_text=res.lrc_text, source=res.source, has_lyrics=True)

        # Если точного совпадения нет, пробуем автоматический поиск через search API
        # (только если есть LrcLibSource)
        lrclib_source = next((src for src in self.sources if isinstance(src, LrcLibSource)), None)
        if lrclib_source:
            logger.info("Точное совпадение не найдено, пробуем поиск для %s", track.display)
            search_results = self._auto_search_fallback(track)
            if search_results:
                best_match = self._find_best_match(track, search_results)
                if best_match:
                    # Сначала пробуем синхронизированные лирики
                    lrc_text = best_match.synced_lyrics_text
                    if not lrc_text and best_match.has_synced_lyrics:
                        # Если текста нет в результате, пробуем обычный fetch
                        lrc_text = self._fetch_lyrics_by_search_result(best_match)
                    
                    # Если синхронизированных нет, но есть обычный текст - используем его
                    if not lrc_text and best_match.has_plain_lyrics:
                        lrc_text = best_match.plain_lyrics_text
                    
                    if lrc_text:
                        self.cache.set(key, has_lyrics=True, lrc_text=lrc_text, source="lrclib_search")
                        return LyricsResponse(lrc_text=lrc_text, source="lrclib_search", has_lyrics=True)

        # negative cache to avoid hammering
        self.cache.set(key, has_lyrics=False, lrc_text=None, source=None)
        return LyricsResponse(lrc_text=None, source=None, has_lyrics=False)

    def _auto_search_fallback(self, track: TrackKey) -> list[SearchResult]:
        """Автоматический поиск при отсутствии точного совпадения."""
        # Пробуем поиск по комбинации artist + title
        query = f"{track.artist} {track.title}".strip()
        if not query:
            return []
        
        results = self.search(q=query, track_name=track.title, artist_name=track.artist)
        return results

    def _find_best_match(self, track: TrackKey, results: list[SearchResult]) -> SearchResult | None:
        """Находит лучший результат поиска по совпадению artist/title."""
        if not results:
            return None

        # Приоритет: точное совпадение artist + title, затем по artist, затем по title
        track_artist_lower = track.artist.lower().strip()
        track_title_lower = track.title.lower().strip()

        best_score = -1
        best_result: SearchResult | None = None

        for r in results:
            score = 0
            r_artist_lower = r.artist_name.lower().strip()
            r_title_lower = r.track_name.lower().strip()

            # Точное совпадение artist и title
            if r_artist_lower == track_artist_lower and r_title_lower == track_title_lower:
                score = 100
            # Совпадение artist и частичное title
            elif r_artist_lower == track_artist_lower:
                score = 50
            # Совпадение title и частичное artist
            elif r_title_lower == track_title_lower:
                score = 30
            # Частичное совпадение
            elif track_artist_lower in r_artist_lower or r_artist_lower in track_artist_lower:
                score = 20
            elif track_title_lower in r_title_lower or r_title_lower in track_title_lower:
                score = 10

            # Бонус за наличие синхронизированных лириков (приоритет)
            if r.has_synced_lyrics:
                score += 5
            # Бонус за наличие обычных лириков (если нет синхронизированных)
            elif r.has_plain_lyrics:
                score += 2

            if score > best_score:
                best_score = score
                best_result = r

        return best_result if best_score > 0 else None

    def _fetch_lyrics_by_search_result(self, result: SearchResult) -> str | None:
        """Получает syncedLyrics для результата поиска через обычный fetch."""
        if not result.has_synced_lyrics:
            return None

        # Используем найденные artist/title для обычного fetch
        track = TrackKey(artist=result.artist_name, title=result.track_name, album=result.album_name)
        for src in self.sources:
            if isinstance(src, LrcLibSource):
                fetch_res = src.fetch(track)
                if fetch_res.lrc_text:
                    return fetch_res.lrc_text
        return None

    def search(
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
                    src.search(
                        q=q,
                        track_name=track_name,
                        artist_name=artist_name,
                        album_name=album_name,
                    )
                )
                # Пока используем только первый источник с поддержкой поиска
                break
        return results

