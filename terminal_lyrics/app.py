from __future__ import annotations

import logging
import signal
import time

from terminal_lyrics.config import AppConfig
from terminal_lyrics.lrc.parse import parse_lrc
from terminal_lyrics.mpris.client import MprisClient
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable
from terminal_lyrics.render.ansi import AnsiRenderer
from terminal_lyrics.sources.service import LyricsService
from terminal_lyrics.sources.types import TrackKey
from terminal_lyrics.sync.tracker import LineTracker

logger = logging.getLogger(__name__)


def watch(cfg: AppConfig, *, preferred_player: str | None, debug: bool) -> int:
    """
    Main watch loop:
    MPRIS -> (track, position) -> lyrics -> parse -> bisect -> render on change.
    """
    svc = LyricsService(cfg)

    renderer = AnsiRenderer(use_alt_screen=cfg.use_alt_screen)
    renderer.enter()
    
    # Handle SIGINT (Ctrl+C) gracefully
    def _on_sigint(signum, frame):
        renderer.exit()
        raise KeyboardInterrupt
    
    signal.signal(signal.SIGINT, _on_sigint)
    
    try:
        last_track_key: str | None = None
        last_rendered_plain: str | None = None
        tracker: LineTracker | None = None
        timed_lines: list[str] = []

        tick_s = 1.0 / max(cfg.refresh_hz, 1.0)

        while True:
            try:
                client = MprisClient.pick_player(preferred=preferred_player)
            except NoPlayersFound:
                renderer.render("terminal-lyrics", ["Нет активных MPRIS-плееров"], current_idx=-1)
                time.sleep(1.0)
                continue

            try:
                ti = client.track_info()
            except PlayerUnavailable as e:
                renderer.render("terminal-lyrics", [f"MPRIS недоступен: {e}"], current_idx=-1)
                time.sleep(0.5)
                continue

            if not ti.title or not ti.artist:
                renderer.render("terminal-lyrics", ["Не удалось получить artist/title из MPRIS"], current_idx=-1)
                time.sleep(0.5)
                continue

            # track changed?
            if ti.track_key != last_track_key:
                last_track_key = ti.track_key
                last_rendered_plain = None
                tracker = None
                timed_lines = []

                track = TrackKey(artist=ti.artist, title=ti.title, album=ti.album)
                res = svc.get_lyrics(track)
                if not res.has_lyrics or not res.lrc_text:
                    renderer.render(track.display, ["Слова не найдены для текущего трека"], current_idx=-1)
                    time.sleep(0.5)
                    continue

                doc = parse_lrc(res.lrc_text)
                if doc.events:
                    tracker = LineTracker.from_events(doc.events)
                    timed_lines = [e.text for e in doc.events]
                    # initial render
                    renderer.render(track.display, timed_lines, current_idx=-1, context_lines=cfg.context_lines)
                else:
                    # plain text lyrics: render once with unsynced indicator
                    plain_lines = [ln.rstrip() for ln in res.lrc_text.splitlines()]
                    last_rendered_plain = "\n".join(plain_lines)
                    # Add visual indicator for unsynced lyrics
                    title_with_indicator = (
                        f"{track.display} {renderer.theme.warning}[несинхронизированный текст]{renderer.theme.reset}"
                    )
                    renderer.render(title_with_indicator, plain_lines, current_idx=-1, context_lines=cfg.context_lines)

            # synced mode
            if tracker is not None:
                try:
                    pos_ms = client.position_ms()
                except PlayerUnavailable:
                    # if player briefly unavailable, don't crash; keep last frame
                    time.sleep(tick_s)
                    continue

                changed = tracker.changed_index(pos_ms)
                if changed is not None:
                    renderer.render(f"{ti.artist} - {ti.title}", timed_lines, current_idx=changed, context_lines=cfg.context_lines)

            time.sleep(tick_s)
    finally:
        renderer.exit()

