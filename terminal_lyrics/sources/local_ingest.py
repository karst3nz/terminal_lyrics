from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import parse_qs, urlparse

from aiohttp import web

from terminal_lyrics.cache.sqlite import CacheKey

logger = logging.getLogger(__name__)

_CORS_BASE = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Max-Age", "86400"),
)


def _cors_headers(request: web.Request) -> dict[str, str]:
    h = {k: v for k, v in _CORS_BASE}
    req_h = request.headers.get("Access-Control-Request-Headers")
    h["Access-Control-Allow-Headers"] = req_h if req_h else "Content-Type"
    return h


def _ingest_route_path(request_target: str) -> str:
    """
    Map request-target (path or absolute URL) to a canonical route: /, /health, /lyrics.
    Handles trailing slashes and case (e.g. /Health/, http://127.0.0.1:7777/health).
    """
    path = urlparse(request_target).path or "/"
    path = path.rstrip("/") or "/"
    if path == "/":
        return "/"
    first = path.lstrip("/").split("/", 1)[0].lower()
    if first == "health":
        return "/health"
    if first == "lyrics":
        return "/lyrics"
    return path


def _cache_key_from_params(
    artist: str | None, title: str | None, album: str | None
) -> CacheKey | None:
    if not artist or not title:
        return None
    return CacheKey(artist=artist.strip(), title=title.strip(), album=(album or "").strip())


class LocalLyricsStore:
    """In-memory lyrics keyed like the SQLite cache; wait/notify for ingest priority."""

    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._lyrics: dict[tuple[str, str, str], str] = {}
        self._unbound_posted_seq = 0
        self._unbound_consumed_seq = 0
        self._unbound_pending: str | None = None
        self._unbound_posted_at = 0.0

    @staticmethod
    def key_tuple(key: CacheKey) -> tuple[str, str, str]:
        return (key.artist, key.title, key.album)

    async def set_lyrics(self, key: CacheKey, text: str) -> None:
        async with self._cond:
            self._lyrics[self.key_tuple(key)] = text
            self._cond.notify_all()
        logger.debug("Local ingest: stored lyrics for %s - %s", key.artist, key.title)

    async def set_unbound_lyrics(self, text: str) -> None:
        """Lyrics without artist/title — matched to whoever is waiting (e.g. browser extension)."""
        async with self._cond:
            self._unbound_posted_seq += 1
            self._unbound_pending = text
            self._unbound_posted_at = time.monotonic()
            self._cond.notify_all()
        logger.debug("Local ingest: unbound lyrics chunk (%s chars)", len(text))

    async def get_lyrics(self, key: CacheKey) -> str | None:
        async with self._cond:
            return self._lyrics.get(self.key_tuple(key))

    def _discard_stale_unbound(self, max_age_s: float) -> None:
        if self._unbound_pending is None:
            return
        if time.monotonic() - self._unbound_posted_at <= max_age_s:
            return
        self._unbound_consumed_seq = self._unbound_posted_seq
        self._unbound_pending = None

    async def wait_for_lyrics(self, key: CacheKey, timeout: float) -> str | None:
        """Wait until lyrics for this track appear or timeout (seconds)."""
        deadline = time.monotonic() + timeout
        kt = self.key_tuple(key)
        stale_s = max(timeout * 2, 45.0)
        async with self._cond:
            self._discard_stale_unbound(stale_s)
            need_seq = self._unbound_consumed_seq
            while True:
                hit = self._lyrics.get(kt)
                if hit is not None:
                    return hit
                if self._unbound_posted_seq > need_seq and self._unbound_pending is not None:
                    text = self._unbound_pending
                    self._unbound_pending = None
                    self._unbound_consumed_seq = self._unbound_posted_seq
                    self._lyrics[kt] = text
                    return text
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue


_STORE_KEY = web.AppKey("terminal_lyrics_ingest_store", LocalLyricsStore)


def _json_error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status, headers=dict(_CORS_BASE))


async def _handle_options(request: web.Request) -> web.Response:
    return web.Response(status=204, headers=_cors_headers(request))


async def _handle_get_health(request: web.Request) -> web.Response:
    route = _ingest_route_path(str(request.rel_url))
    if route not in ("/", "/health"):
        return _json_error(404, "Not Found")
    return web.json_response({"status": "ok"}, headers=dict(_CORS_BASE))


async def _handle_head_health(request: web.Request) -> web.Response:
    route = _ingest_route_path(str(request.rel_url))
    if route not in ("/", "/health"):
        return web.Response(status=404)
    return web.Response(
        status=200,
        headers={**dict(_CORS_BASE), "Content-Type": "application/json; charset=utf-8"},
    )


async def _handle_post(request: web.Request) -> web.Response:
    store: LocalLyricsStore = request.app[_STORE_KEY]
    route = _ingest_route_path(str(request.rel_url))
    if route not in ("/", "/lyrics"):
        return _json_error(404, "Not Found")

    body = await request.read()
    ctype = (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()

    key: CacheKey | None = None
    lrc_text: str | None = None

    parsed = urlparse(str(request.rel_url))
    qs = parse_qs(parsed.query)
    q_artist = (qs.get("artist") or [None])[0]
    q_title = (qs.get("title") or [None])[0]
    q_album = (qs.get("album") or [None])[0]

    if ctype == "application/json":
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "ingest %s POST %s: invalid JSON (%d bytes)",
                request.remote,
                request.rel_url,
                len(body),
            )
            return _json_error(400, "Invalid JSON")
        if not isinstance(data, dict):
            logger.warning(
                "ingest %s POST %s: JSON root must be object",
                request.remote,
                request.rel_url,
            )
            return _json_error(400, "JSON object expected")
        artist = data.get("artist") or q_artist
        title = data.get("title") or q_title
        album = data.get("album") or q_album
        key = _cache_key_from_params(
            str(artist) if artist is not None else None,
            str(title) if title is not None else None,
            str(album) if album is not None else None,
        )
        lrc_text = data.get("lrc_text") or data.get("lyrics") or data.get("text")
        if isinstance(lrc_text, str):
            pass
        else:
            lrc_text = None
    else:
        key = _cache_key_from_params(
            str(q_artist) if q_artist else None,
            str(q_title) if q_title else None,
            str(q_album) if q_album else None,
        )
        try:
            lrc_text = body.decode("utf-8") if body else None
        except UnicodeDecodeError:
            logger.warning(
                "ingest %s POST %s: body is not UTF-8",
                request.remote,
                request.rel_url,
            )
            return _json_error(400, "Body must be UTF-8")

    if not lrc_text or not lrc_text.strip():
        logger.warning(
            "ingest %s POST %s: missing lyrics text",
            request.remote,
            request.rel_url,
        )
        return _json_error(
            400, "lyrics text required (JSON lyrics / lrc_text / text or body)"
        )

    if key is not None:
        await store.set_lyrics(key, lrc_text)
        logger.info(
            "ingest %s: accepted lyrics for %s - %s (%d chars, %s)",
            request.remote,
            key.artist,
            key.title,
            len(lrc_text),
            ctype or "no-content-type",
        )
        out = {"ok": True, "artist": key.artist, "title": key.title}
    else:
        if ctype != "application/json":
            logger.warning(
                "ingest %s POST %s: artist/title required for non-JSON",
                request.remote,
                request.rel_url,
            )
            return _json_error(
                400,
                "artist and title required for non-JSON POST (use query or JSON fields)",
            )
        await store.set_unbound_lyrics(lrc_text)
        logger.info(
            "ingest %s: accepted unbound lyrics (%d chars)",
            request.remote,
            len(lrc_text),
        )
        out = {"ok": True, "mode": "unbound"}
    return web.json_response(out, headers=dict(_CORS_BASE))


async def start_ingest_server_async(
    host: str, port: int
) -> tuple[LocalLyricsStore, web.AppRunner, web.TCPSite]:
    """
    Start aiohttp ingest server on the current asyncio event loop.

    Returns ``(store, runner, site)`` for ``await site.stop()`` / ``await runner.cleanup()``.
    """
    store = LocalLyricsStore()
    app = web.Application()
    app[_STORE_KEY] = store
    for path in ("/", "/health", "/lyrics"):
        app.router.add_options(path, _handle_options)
    app.router.add_get("/", _handle_get_health)
    app.router.add_get("/health", _handle_get_health)
    app.router.add_head("/", _handle_head_health)
    app.router.add_head("/health", _handle_head_health)
    app.router.add_post("/", _handle_post)
    app.router.add_post("/lyrics", _handle_post)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port, reuse_address=True)
    await site.start()

    bound = site._server.sockets[0].getsockname() if site._server and site._server.sockets else (host, port)
    logger.info("Local lyrics ingest server listening on http://%s:%s", bound[0], bound[1])
    return store, runner, site
