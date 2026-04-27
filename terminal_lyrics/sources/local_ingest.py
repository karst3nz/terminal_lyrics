from __future__ import annotations

import asyncio
import json
import logging
import time
from urllib.parse import parse_qs, urlparse
from typing import Set

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

    def __init__(self, lyrics_callback: callable = None) -> None:
        self._cond = asyncio.Condition()
        self._lyrics: dict[tuple[str, str, str], str] = {}
        self._unbound_posted_seq = 0
        self._unbound_consumed_seq = 0
        self._unbound_pending: str | None = None
        self._unbound_posted_at = 0.0
        self._ws_connections: Set[web.WebSocketResponse] = set()
        self._lyrics_callback = lyrics_callback

    @staticmethod
    def key_tuple(key: CacheKey) -> tuple[str, str, str]:
        return (key.artist, key.title, key.album)

    async def set_lyrics(self, key: CacheKey, text: str) -> None:
        async with self._cond:
            self._lyrics[self.key_tuple(key)] = text
            self._cond.notify_all()
        logger.debug("Local ingest: stored lyrics for %s - %s", key.artist, key.title)
        if self._lyrics_callback:
            self._lyrics_callback(key, text)
        await self._notify_ws_clients(
            {
                "type": "lyrics_added",
                "artist": key.artist,
                "title": key.title,
                "album": key.album,
                "lyrics_length": len(text),
            }
        )

    async def set_unbound_lyrics(self, text: str) -> None:
        """Lyrics without artist/title — matched to whoever is waiting (e.g. browser extension)."""
        async with self._cond:
            self._unbound_posted_seq += 1
            self._unbound_pending = text
            self._unbound_posted_at = time.monotonic()
            self._cond.notify_all()
        logger.debug("Local ingest: unbound lyrics chunk (%s chars)", len(text))
        await self._notify_ws_clients({"type": "unbound_lyrics_added", "lyrics_length": len(text)})

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

    def add_ws_connection(self, ws: web.WebSocketResponse) -> None:
        """Add a WebSocket connection to the set of active connections."""
        self._ws_connections.add(ws)

    def remove_ws_connection(self, ws: web.WebSocketResponse) -> None:
        """Remove a WebSocket connection from the set of active connections."""
        self._ws_connections.discard(ws)

    async def _notify_ws_clients(self, message: dict) -> None:
        """Send a message to all connected WebSocket clients."""
        if not self._ws_connections:
            return

        # Create a copy of the connections set to avoid issues if connections are removed during iteration
        connections = self._ws_connections.copy()
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception:
                # Connection might be closed, remove it
                self._ws_connections.discard(ws)


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


async def _handle_ws_message(
    ws: web.WebSocketResponse, store: LocalLyricsStore, data: dict, remote: str
) -> None:
    """Handle incoming WebSocket messages."""
    msg_type = data.get("type")

    if msg_type == "send_lyrics":
        # Handle lyrics submission via WebSocket
        artist = data.get("artist")
        title = data.get("title")
        album = data.get("album")
        lrc_text = data.get("lyrics") or data.get("lrc_text") or data.get("text")
        download_url = data.get("downloadUrl")

        if not lrc_text or not lrc_text.strip():
            # If no lyrics text but downloadUrl provided, try fetching
            if download_url:
                try:
                    import aiohttp

                    async with aiohttp.ClientSession() as session:
                        async with session.get(download_url) as resp:
                            if resp.status == 200:
                                fetched_text = await resp.text()
                                if fetched_text.strip():
                                    lrc_text = fetched_text.strip()
                                    logger.debug(
                                        "Fetched lyrics from downloadUrl for %s - %s",
                                        artist or "unknown",
                                        title or "unknown",
                                    )
                                else:
                                    await ws.send_json({"error": "empty lyrics from downloadUrl"})
                                    return
                            else:
                                await ws.send_json(
                                    {"error": f"failed to fetch from downloadUrl: {resp.status}"}
                                )
                                return
                except Exception as e:
                    logger.exception("Error fetching from downloadUrl")
                    await ws.send_json({"error": "failed to fetch lyrics"})
                    return
            else:
                await ws.send_json({"error": "lyrics text required"})
                return

        if artist and title:
            # Regular lyrics with artist/title
            key = _cache_key_from_params(
                str(artist).strip(), str(title).strip(), str(album or "").strip()
            )
            if key:
                await store.set_lyrics(key, lrc_text.strip())
                logger.debug(
                    "WebSocket lyrics received from %s: accepted lyrics for %s - %s (%d chars)",
                    remote,
                    key.artist,
                    key.title,
                    len(lrc_text),
                )
                await ws.send_json(
                    {
                        "ok": True,
                        "type": "lyrics_accepted",
                        "artist": key.artist,
                        "title": key.title,
                    }
                )
            else:
                await ws.send_json({"error": "invalid artist/title"})
        else:
            # Unbound lyrics
            await store.set_unbound_lyrics(lrc_text.strip())
            logger.debug(
                "WebSocket lyrics received from %s: accepted unbound lyrics (%d chars)",
                remote,
                len(lrc_text),
            )
            await ws.send_json({"ok": True, "type": "unbound_lyrics_accepted"})

    elif msg_type == "ping":
        # Simple ping-pong for connection testing
        await ws.send_json({"type": "pong"})

    else:
        await ws.send_json({"error": f"unknown message type: {msg_type}"})


async def _handle_websocket(request: web.Request) -> web.WebSocketResponse:
    """Handle WebSocket connections for real-time lyrics updates."""
    store: LocalLyricsStore = request.app[_STORE_KEY]

    ws = web.WebSocketResponse(heartbeat=30.0)  # Send heartbeat every 30 seconds
    await ws.prepare(request)

    store.add_ws_connection(ws)
    logger.debug("WebSocket connection established from %s", request.remote)

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.ERROR:
                logger.error("WebSocket error from %s: %s", request.remote, ws.exception())
            elif msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await _handle_ws_message(ws, store, data, request.remote)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received from %s: %s", request.remote, msg.data)
                    await ws.send_json({"error": "Invalid JSON"})
                except Exception as e:
                    logger.error(
                        "Error processing WebSocket message from %s: %s", request.remote, e
                    )
                    await ws.send_json({"error": "Internal server error"})
            elif msg.type == web.WSMsgType.CLOSE:
                break
    finally:
        store.remove_ws_connection(ws)
        logger.debug("WebSocket connection closed from %s", request.remote)

    return ws


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
        return _json_error(400, "lyrics text required (JSON lyrics / lrc_text / text or body)")

    if key is not None:
        await store.set_lyrics(key, lrc_text)
        logger.debug(
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
        logger.debug(
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
    app.router.add_get("/ws", _handle_websocket)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port, reuse_address=True)
    await site.start()

    bound = (
        site._server.sockets[0].getsockname()
        if site._server and site._server.sockets
        else (host, port)
    )
    logger.debug("Local lyrics ingest server listening on http://%s:%s", bound[0], bound[1])
    return store, runner, site
