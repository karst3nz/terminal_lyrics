from __future__ import annotations

import logging
import signal
import time

from terminal_lyrics.config import AppConfig
from terminal_lyrics.i18n import set_lang, t
from terminal_lyrics.lrc.parse import parse_lrc
from terminal_lyrics.mpris.client import MprisClient
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable
from terminal_lyrics.render.ansi import AnsiRenderer, EnhancedRenderer, RenderOptions
from terminal_lyrics.sources.service import LyricsService
from terminal_lyrics.sources.types import TrackKey
from terminal_lyrics.sync.tracker import LineTracker

logger = logging.getLogger(__name__)


def watch(cfg: AppConfig, *, preferred_player: str | None, debug: bool) -> int:
    """
    Main watch loop:
    MPRIS -> (track, position) -> lyrics -> parse -> bisect -> render on change.
    """
    set_lang(cfg.lang)
    svc = LyricsService(cfg)

    # Create render options from config
    render_options = RenderOptions(
        theme_name=cfg.visual.theme,
        border_style=cfg.visual.border_style,
        show_progress_bar=cfg.visual.show_progress_bar,
        show_metadata=cfg.visual.show_metadata,
        show_visualizer=cfg.visual.show_visualizer,
        visualizer_style=cfg.visual.visualizer_style,
        visualizer_position=cfg.visual.visualizer_position,
        center_text=cfg.visual.center_text,
        enable_animations=cfg.visual.enable_animations,
        enable_gradient=cfg.visual.enable_gradient,
        enable_pulse=cfg.visual.enable_pulse,
        use_real_audio=cfg.audio.use_real_audio,
        audio_device=cfg.audio.audio_device,
        audio_backend=cfg.audio.audio_backend,
        waveform_style="detailed",  # Can be configured later
    )

    # Use enhanced renderer
    renderer = EnhancedRenderer(
        use_alt_screen=cfg.use_alt_screen,
        options=render_options,
        config_dir=str(cfg.config_dir),
    )
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
                renderer.render("terminal-lyrics", [t("no_mpris_players")], current_idx=-1)
                time.sleep(1.0)
                continue

            try:
                ti = client.track_info()
            except PlayerUnavailable as e:
                renderer.render(
                    "terminal-lyrics", [t("mpris_unavailable", msg=str(e))], current_idx=-1
                )
                time.sleep(0.5)
                continue

            if not ti.title or not ti.artist:
                renderer.render("terminal-lyrics", [t("no_artist_title")], current_idx=-1)
                time.sleep(0.5)
                continue

            # Update playback state for progress bar
            try:
                pos_ms = client.position_ms()
                duration_ms = ti.length_ms
                status = client.playback_status()
                is_playing = status.lower() == "playing"

                renderer.update_playback_state(
                    position=pos_ms / 1000.0,
                    duration=duration_ms / 1000.0,
                    playing=is_playing,
                )
            except (PlayerUnavailable, AttributeError):
                pass

            # track changed?
            if ti.track_key != last_track_key:
                last_track_key = ti.track_key
                last_rendered_plain = None
                tracker = None
                timed_lines = []

                track = TrackKey(artist=ti.artist, title=ti.title, album=ti.album)
                res = svc.get_lyrics(track)
                if not res.has_lyrics or not res.lrc_text:
                    # No lyrics found - set empty tracker to continue rendering
                    tracker = None
                    timed_lines = [t("lyrics_not_found")]
                else:
                    doc = parse_lrc(res.lrc_text)
                    if doc.events:
                        tracker = LineTracker.from_events(doc.events)
                        timed_lines = [e.text for e in doc.events]
                    else:
                        # plain text lyrics: render once with unsynced indicator
                        plain_lines = [ln.rstrip() for ln in res.lrc_text.splitlines()]
                        last_rendered_plain = "\n".join(plain_lines)
                        timed_lines = plain_lines
                        tracker = None

            # Always render to update progress bar and visualizer
            if tracker is not None:
                # Synced lyrics mode
                try:
                    pos_ms = client.position_ms()
                except PlayerUnavailable:
                    # if player briefly unavailable, don't crash; keep last frame
                    time.sleep(tick_s)
                    continue

                current_idx = tracker.current_index(pos_ms)
                renderer.render(
                    f"{ti.artist} - {ti.title}",
                    timed_lines,
                    current_idx=current_idx,
                    context_lines=cfg.context_lines,
                    artist=ti.artist,
                    album=ti.album or "",
                )
            else:
                # No synced lyrics or no lyrics at all - still render for progress bar
                renderer.render(
                    f"{ti.artist} - {ti.title}",
                    timed_lines,
                    current_idx=-1,
                    context_lines=cfg.context_lines,
                    artist=ti.artist,
                    album=ti.album or "",
                )

            time.sleep(tick_s)
    finally:
        renderer.exit()
