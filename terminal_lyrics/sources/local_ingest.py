from __future__ import annotations

import json
import logging
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from terminal_lyrics.cache.sqlite import CacheKey

logger = logging.getLogger(__name__)

_CORS_HEADERS = (
    ("Access-Control-Allow-Origin", "*"),
    ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
    ("Access-Control-Max-Age", "86400"),
)


def _send_cors(handler: BaseHTTPRequestHandler) -> None:
    for name, value in _CORS_HEADERS:
        handler.send_header(name, value)


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
        self._cv = threading.Condition()
        self._lyrics: dict[tuple[str, str, str], str] = {}
        # Unbound payloads (e.g. Yandex bridge JSON with only "lyrics") — one pending slot, latest wins.
        self._unbound_posted_seq = 0
        self._unbound_consumed_seq = 0
        self._unbound_pending: str | None = None
        self._unbound_posted_at = 0.0

    @staticmethod
    def key_tuple(key: CacheKey) -> tuple[str, str, str]:
        return (key.artist, key.title, key.album)

    def set_lyrics(self, key: CacheKey, text: str) -> None:
        with self._cv:
            self._lyrics[self.key_tuple(key)] = text
            self._cv.notify_all()
        logger.debug("Local ingest: stored lyrics for %s - %s", key.artist, key.title)

    def set_unbound_lyrics(self, text: str) -> None:
        """Lyrics without artist/title — matched to whoever is waiting (e.g. browser extension)."""
        with self._cv:
            self._unbound_posted_seq += 1
            self._unbound_pending = text
            self._unbound_posted_at = time.monotonic()
            self._cv.notify_all()
        logger.debug("Local ingest: unbound lyrics chunk (%s chars)", len(text))

    def get_lyrics(self, key: CacheKey) -> str | None:
        with self._cv:
            return self._lyrics.get(self.key_tuple(key))

    def _discard_stale_unbound(self, max_age_s: float) -> None:
        if self._unbound_pending is None:
            return
        if time.monotonic() - self._unbound_posted_at <= max_age_s:
            return
        self._unbound_consumed_seq = self._unbound_posted_seq
        self._unbound_pending = None

    def wait_for_lyrics(self, key: CacheKey, timeout: float) -> str | None:
        """Block until lyrics for this track appear or timeout (seconds)."""
        deadline = time.monotonic() + timeout
        kt = self.key_tuple(key)
        stale_s = max(timeout * 2, 45.0)
        with self._cv:
            self._discard_stale_unbound(stale_s)
            need_seq = self._unbound_consumed_seq
            while True:
                hit = self._lyrics.get(kt)
                if hit is not None:
                    return hit
                if (
                    self._unbound_posted_seq > need_seq
                    and self._unbound_pending is not None
                ):
                    text = self._unbound_pending
                    self._unbound_pending = None
                    self._unbound_consumed_seq = self._unbound_posted_seq
                    self._lyrics[kt] = text
                    return text
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cv.wait(timeout=remaining)


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0
    if length <= 0:
        return b""
    return handler.rfile.read(length)


def _make_handler(store: LocalLyricsStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            logger.info("ingest %s - " + fmt, self.address_string(), *args)

        def log_error(self, fmt: str, *args: object) -> None:
            logger.warning("ingest %s - " + fmt, self.address_string(), *args)

        def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
            if isinstance(code, HTTPStatus):
                code = code.value
            line = '"%s" %s %s' % (self.requestline, str(code), str(size))
            route = _ingest_route_path(self.path)
            quiet_probe = self.command in ("GET", "HEAD") and route in ("/", "/health")
            if quiet_probe:
                logger.debug("ingest %s %s", self.address_string(), line)
            else:
                logger.info("ingest %s %s", self.address_string(), line)

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            _send_cors(self)
            req_h = self.headers.get("Access-Control-Request-Headers")
            self.send_header(
                "Access-Control-Allow-Headers",
                req_h if req_h else "Content-Type",
            )
            self.end_headers()

        def do_GET(self) -> None:
            route = _ingest_route_path(self.path)
            if route not in ("/", "/health"):
                logger.warning(
                    "ingest %s GET %s -> 404", self.address_string(), self.path
                )
                self.send_error(404, "Not Found")
                return
            payload = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            _send_cors(self)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_HEAD(self) -> None:
            route = _ingest_route_path(self.path)
            if route not in ("/", "/health"):
                self.send_error(404, "Not Found")
                return
            payload = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            _send_cors(self)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            route = _ingest_route_path(self.path)
            if route not in ("/", "/lyrics"):
                logger.warning(
                    "ingest %s POST %s -> 404", self.address_string(), self.path
                )
                self.send_error(404, "Not Found")
                return

            body = _read_body(self)
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()

            key: CacheKey | None = None
            lrc_text: str | None = None

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
                        self.address_string(),
                        self.path,
                        len(body),
                    )
                    self.send_error(400, "Invalid JSON")
                    return
                if not isinstance(data, dict):
                    logger.warning(
                        "ingest %s POST %s: JSON root must be object",
                        self.address_string(),
                        self.path,
                    )
                    self.send_error(400, "JSON object expected")
                    return
                artist = data.get("artist") or q_artist
                title = data.get("title") or q_title
                album = data.get("album") or q_album
                key = _cache_key_from_params(
                    str(artist) if artist is not None else None,
                    str(title) if title is not None else None,
                    str(album) if album is not None else None,
                )
                # Yandex-style bridge: { "apiUrl", "downloadUrl", "lyrics": "[00:01]..." }
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
                        self.address_string(),
                        self.path,
                    )
                    self.send_error(400, "Body must be UTF-8")
                    return

            if not lrc_text or not lrc_text.strip():
                logger.warning(
                    "ingest %s POST %s: missing lyrics text",
                    self.address_string(),
                    self.path,
                )
                self.send_error(400, "lyrics text required (JSON lyrics / lrc_text / text or body)")
                return

            if key is not None:
                store.set_lyrics(key, lrc_text)
                logger.info(
                    "ingest %s: accepted lyrics for %s - %s (%d chars, %s)",
                    self.address_string(),
                    key.artist,
                    key.title,
                    len(lrc_text),
                    ctype or "no-content-type",
                )
                out = json.dumps(
                    {"ok": True, "artist": key.artist, "title": key.title}
                ).encode("utf-8")
            else:
                if ctype != "application/json":
                    logger.warning(
                        "ingest %s POST %s: artist/title required for non-JSON",
                        self.address_string(),
                        self.path,
                    )
                    self.send_error(
                        400,
                        "artist and title required for non-JSON POST (use query or JSON fields)",
                    )
                    return
                store.set_unbound_lyrics(lrc_text)
                logger.info(
                    "ingest %s: accepted unbound lyrics (%d chars)",
                    self.address_string(),
                    len(lrc_text),
                )
                out = json.dumps({"ok": True, "mode": "unbound"}).encode("utf-8")
            self.send_response(200)
            _send_cors(self)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    return Handler


class IngestHTTPServer(HTTPServer):
    """SO_REUSEADDR so a quick restart can re-bind the same ingest port."""

    allow_reuse_address = True


def start_ingest_server(
    host: str, port: int
) -> tuple[LocalLyricsStore, threading.Thread, HTTPServer]:
    """
    Bind the HTTP server, then run ``serve_forever`` in a daemon thread.

    Returns immediately so the caller (e.g. ``watch``) can run the terminal UI
    loop on the main thread in parallel with request handling.
    """
    store = LocalLyricsStore()
    handler_cls = _make_handler(store)
    httpd = IngestHTTPServer((host, port), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True, name="lyrics-ingest")
    thread.start()
    logger.info("Local lyrics ingest server listening on http://%s:%s", host, port)
    return store, thread, httpd
