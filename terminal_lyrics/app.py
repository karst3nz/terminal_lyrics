from __future__ import annotations

from dataclasses import replace
import asyncio
import logging
import math
import shutil
import signal
import time

from terminal_lyrics.config import AppConfig, save_visual_config
from terminal_lyrics.i18n import set_lang, t
from terminal_lyrics.lrc.parse import parse_lrc
from terminal_lyrics.mpris import async_dbus as mpris_async
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable
from terminal_lyrics.render.ansi import (
    AnsiRenderer,
    EnhancedRenderer,
    RenderOptions,
    media_controls_layout,
)
from terminal_lyrics.render.layout import (
    ICON_PAUSED,
    ICON_PLAYING,
    _display_width,
    format_time,
    wrap_text,
)
from terminal_lyrics.sources.attribution import format_lyrics_source_footer
from terminal_lyrics.sources.service import LyricsService
from terminal_lyrics.sources.types import TrackKey
from terminal_lyrics.sync.tracker import LineTracker

logger = logging.getLogger(__name__)
VISUALIZER_STYLES: tuple[str, ...] = ("equalizer", "waveform", "blocks", "dots", "centered")


async def _handle_mouse_action(action: str, player_service: str) -> None:
    """Execute a mouse click action on the MPRIS player (D-Bus via background thread)."""
    try:
        if action == "prev":
            logger.debug("Mouse action: previous_track")
            await mpris_async.previous_track(player_service)
        elif action == "play_pause":
            logger.debug("Mouse action: play_pause")
            await mpris_async.play_pause(player_service)
        elif action == "next":
            logger.debug("Mouse action: next_track")
            await mpris_async.next_track(player_service)
    except Exception as e:
        logger.exception("Failed to execute mouse action '%s': %s", action, e)


def _clamp_scroll_offset(
    *,
    scroll_offset: int,
    current_idx: int,
    context_lines: int,
    total_lines: int,
) -> int:
    """Clamp manual lyrics scroll around the auto-follow anchor."""
    if total_lines <= 0:
        return 0

    base_start = 0 if current_idx < 0 else max(current_idx - context_lines, 0)
    max_start = max(total_lines - 1, 0)
    min_offset = -base_start
    max_offset = max_start - base_start
    return max(min_offset, min(scroll_offset, max_offset))


def _compute_layout_info(
    cols: int,
    rows: int,
    options: RenderOptions,
    *,
    has_progress_line: bool,
    lyrics_footer_lines: int = 0,
) -> dict[str, int | None]:
    """Compute key layout rows to map mouse clicks to UI zones."""
    header_lines = 1
    top_offset = 1  # line after top border

    top_visualizer_start = None
    top_visualizer_end = None
    bottom_visualizer_start = None
    bottom_visualizer_end = None

    if options.show_visualizer and options.visualizer_position == "top":
        top_visualizer_start = top_offset
        top_visualizer_end = top_offset + 2
        top_offset += 4
        header_lines += 4

    title_row = top_offset if options.show_metadata else None

    progress_row = None
    controls_row = None
    metadata_block_lines = 0
    if options.show_metadata:
        # Metadata block in renderer:
        # - always title line
        # - optional separator + progress (+ optional controls) when progress is shown
        # - always closing separator
        metadata_block_lines += 1  # title
        if options.show_progress_bar and has_progress_line:
            progress_row = top_offset + 2
            metadata_block_lines += 2  # separator before progress + progress line
            if options.show_media_controls:
                controls_row = top_offset + 3
                metadata_block_lines += 1  # controls line
        metadata_block_lines += 1  # closing separator
        header_lines += metadata_block_lines

    footer_lines = 4 if options.show_visualizer and options.visualizer_position == "bottom" else 0
    if options.show_visualizer and options.visualizer_position == "bottom":
        bottom_visualizer_start = rows - 4
        bottom_visualizer_end = rows - 2
    body_rows = max(rows - header_lines - footer_lines - 2, 1)
    lyric_body_rows = max(0, body_rows - lyrics_footer_lines)
    lyrics_row_start = top_offset + (metadata_block_lines if options.show_metadata else 0)
    lyrics_row_end = (
        lyrics_row_start + lyric_body_rows - 1 if lyric_body_rows > 0 else lyrics_row_start - 1
    )

    return {
        "title_row": title_row,
        "progress_row": progress_row,
        "controls_row": controls_row,
        "top_visualizer_start": top_visualizer_start,
        "top_visualizer_end": top_visualizer_end,
        "bottom_visualizer_start": bottom_visualizer_start,
        "bottom_visualizer_end": bottom_visualizer_end,
        "lyrics_row_start": lyrics_row_start,
        "lyrics_row_end": lyrics_row_end,
        "body_rows": lyric_body_rows,
    }


def _next_visualizer_style(current: str) -> str:
    """Cycle visualizer style to the next supported value."""
    try:
        idx = VISUALIZER_STYLES.index(current)
    except ValueError:
        return VISUALIZER_STYLES[0]
    return VISUALIZER_STYLES[(idx + 1) % len(VISUALIZER_STYLES)]


def _visible_lyrics_mapping(
    *,
    lines: list[str],
    current_idx: int,
    context_lines: int,
    scroll_offset: int,
    max_text_width: int,
    body_rows: int,
) -> list[int]:
    """Map visible wrapped rows to original lyric line indices."""
    if body_rows <= 0:
        return []
    if current_idx < 0:
        base_start = 0
    else:
        base_start = max(current_idx - context_lines, 0)
    start = max(0, base_start + scroll_offset)

    wrapped_idx: list[int] = []
    for i in range(start, len(lines)):
        wrapped = wrap_text(lines[i], max_text_width)
        for _ in wrapped:
            wrapped_idx.append(i)
            if len(wrapped_idx) >= body_rows:
                return wrapped_idx
    return wrapped_idx


def _progress_bar_click_bounds(
    *, cols: int, current_s: float, total_s: float, is_playing: bool
) -> tuple[int, int] | None:
    """Return inclusive x-bounds for the visible progress bar (0-based screen coords)."""
    if total_s <= 0 or cols <= 3:
        return None

    time_current = format_time(current_s)
    time_total = format_time(total_s)
    time_str = f"{time_current} / {time_total}"

    # Keep math aligned with EnhancedRenderer.render()
    time_width = len(time_str) + 3  # icon + spaces + time
    bar_width = max(10, cols - time_width - 4)
    inner_width = max(0, cols - 2)  # without borders

    status_icon = ICON_PLAYING if is_playing else ICON_PAUSED
    prefix_width = _display_width(status_icon) + 1  # icon + trailing space
    progress_line_width = prefix_width + bar_width + 1 + len(time_str)
    left_pad = max(0, inner_width - progress_line_width) // 2

    bar_start_x = 1 + left_pad + prefix_width
    bar_end_x = bar_start_x + bar_width - 1
    bar_start_x = max(1, min(bar_start_x, cols - 2))
    bar_end_x = max(1, min(bar_end_x, cols - 2))
    if bar_end_x < bar_start_x:
        return None
    return bar_start_x, bar_end_x


async def watch(cfg: AppConfig, *, preferred_player: str | None, debug: bool) -> int:
    """
    Main watch loop:
    MPRIS -> (track, position) -> lyrics -> parse -> bisect -> render on change.

    Lyrics ingest (optional): when enabled, an aiohttp server runs on the same
    asyncio event loop as this UI loop.
    """
    set_lang(cfg.lang)

    ingest_runner = None
    ingest_site = None
    ingest_store = None
    if cfg.ingest_enabled:
        from terminal_lyrics.sources.local_ingest import start_ingest_server_async

        try:
            ingest_store, ingest_runner, ingest_site = await start_ingest_server_async(
                cfg.ingest_host, cfg.ingest_port
            )
        except OSError as exc:
            logger.warning(
                "Lyrics ingest server not started (%s:%s): %s. "
                "If the address is already in use, stop the other process or set "
                "TERMINAL_LYRICS_INGEST_PORT to a free port.",
                cfg.ingest_host,
                cfg.ingest_port,
                exc,
            )
            ingest_store = None
            ingest_runner = None
            ingest_site = None
    elif debug:
        logger.debug(
            "Lyrics ingest HTTP server is off (TERMINAL_LYRICS_INGEST=0). It is enabled by default."
        )

    svc = LyricsService(cfg, local_ingest_store=ingest_store)

    # Create render options from config
    render_options = RenderOptions(
        theme_name=cfg.visual.theme,
        border_style=cfg.visual.border_style,
        show_progress_bar=cfg.visual.show_progress_bar,
        show_metadata=cfg.visual.show_metadata,
        show_media_controls=cfg.enable_media_controls,
        show_visualizer=cfg.visual.show_visualizer,
        visualizer_style=cfg.visual.visualizer_style,
        visualizer_motion=cfg.visual.visualizer_motion,
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

    # Initialize mouse handler if enabled
    mouse_handler = None
    if cfg.enable_mouse:
        logger.debug(f"Mouse support enabled, initializing handler...")
        try:
            from terminal_lyrics.mouse_input import MouseControlsHandler, MouseProtocol

            mouse_handler = MouseControlsHandler(
                client=None,  # Will pass client per-call
                rows=0,  # Will be calculated per-frame
                cols=0,
                protocol=MouseProtocol.SGR,
            )
            mouse_handler.enter()
            logger.debug("Mouse handler initialized, enabled=%s", mouse_handler._enabled)
        except Exception:
            logger.exception("Failed to initialize mouse handler, disabling mouse support")
            mouse_handler = None
    else:
        logger.debug("Mouse support disabled in config")

    # Setup lyrics update callback for WebSocket ingest
    lyrics_update_event = asyncio.Event()
    new_lyrics_key = None
    new_lyrics_text = None

    def lyrics_callback(key, text):
        nonlocal new_lyrics_key, new_lyrics_text
        new_lyrics_key = key
        new_lyrics_text = text
        lyrics_update_event.set()

    if ingest_store is not None:
        ingest_store._lyrics_callback = lyrics_callback

    media_controls_enabled = cfg.enable_media_controls

    # Handle SIGINT (Ctrl+C) gracefully
    def _on_sigint(signum, frame):
        if mouse_handler:
            mouse_handler.exit()
        renderer.exit()
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _on_sigint)

    try:
        last_track_key: str | None = None
        last_rendered_plain: str | None = None
        tracker: LineTracker | None = None
        timed_lines: list[str] = []
        timed_line_times_ms: list[int] = []
        lyrics_scroll_offset = 0
        last_scroll_action_at: float | None = None
        click_highlight_idx: int | None = None
        click_highlight_until: float | None = None
        hover_highlight_idx: int | None = None
        hover_highlight_since: float | None = None
        status_notice: str | None = None
        status_notice_until: float | None = None
        active_player_name: str | None = None
        lyrics_source_line: str | None = None

        tick_s = 1.0 / max(cfg.refresh_hz, 1.0)

        while True:
            try:
                if active_player_name:
                    await mpris_async.probe_player(active_player_name)
                else:
                    active_player_name = await mpris_async.pick_player_service_name(
                        preferred_player
                    )
            except Exception:
                # Active player disappeared or became invalid: repick.
                active_player_name = None
                try:
                    active_player_name = await mpris_async.pick_player_service_name(
                        preferred_player
                    )
                except NoPlayersFound:
                    renderer.render("terminal_lyrics", [t("no_mpris_players")], current_idx=-1)
                    await asyncio.sleep(1.0)
                    continue
            try:
                ti = await mpris_async.track_info(active_player_name)
            except PlayerUnavailable as e:
                renderer.render(
                    "terminal_lyrics", [t("mpris_unavailable", msg=str(e))], current_idx=-1
                )
                await asyncio.sleep(0.5)
                continue

            if not ti.title or not ti.artist:
                renderer.render("terminal_lyrics", [t("no_artist_title")], current_idx=-1)
                await asyncio.sleep(0.5)
                continue

            # Update playback state for progress bar
            try:
                pos_ms = await mpris_async.position_ms(active_player_name)
                duration_ms = ti.length_ms
                status = await mpris_async.playback_status(active_player_name)
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
                timed_line_times_ms = []
                lyrics_scroll_offset = 0
                last_scroll_action_at = None
                click_highlight_idx = None
                click_highlight_until = None
                hover_highlight_idx = None
                hover_highlight_since = None
                status_notice = None
                status_notice_until = None
                lyrics_source_line = None

                track = TrackKey(artist=ti.artist, title=ti.title, album=ti.album)
                res = await svc.get_lyrics(track)
                if not res.has_lyrics or not res.lrc_text:
                    # No lyrics found - set empty tracker to continue rendering
                    tracker = None
                    timed_lines = [t("lyrics_not_found")]
                else:
                    lyrics_source_line = format_lyrics_source_footer(res.source)
                    doc = parse_lrc(res.lrc_text)
                    if doc.events:
                        tracker = LineTracker.from_events(doc.events)
                        timed_lines = [e.text for e in doc.events]
                        timed_line_times_ms = [e.t_ms for e in doc.events]
                    else:
                        # plain text lyrics: render once with unsynced indicator
                        plain_lines = [ln.rstrip() for ln in res.lrc_text.splitlines()]
                        last_rendered_plain = "\n".join(plain_lines)
                        timed_lines = plain_lines
                        timed_line_times_ms = []
                        tracker = None

            # Always render to update progress bar and visualizer
            render_current_idx = -1
            if click_highlight_until is not None and time.monotonic() >= click_highlight_until:
                click_highlight_idx = None
                click_highlight_until = None
            if status_notice_until is not None and time.monotonic() >= status_notice_until:
                status_notice = None
                status_notice_until = None
            if tracker is not None:
                # Synced lyrics mode
                try:
                    pos_ms = await mpris_async.position_ms(active_player_name)
                except PlayerUnavailable:
                    # if player briefly unavailable, don't crash; keep last frame
                    await asyncio.sleep(tick_s)
                    continue

                current_idx = tracker.current_index(pos_ms)
                render_current_idx = current_idx
                renderer.render(
                    f"{ti.artist} - {ti.title}",
                    timed_lines,
                    current_idx=current_idx,
                    context_lines=cfg.context_lines,
                    scroll_offset=lyrics_scroll_offset,
                    artist=ti.artist,
                    album=ti.album or "",
                    click_highlight_idx=click_highlight_idx,
                    hover_highlight_idx=hover_highlight_idx,
                    status_notice=status_notice,
                    lyrics_source_line=lyrics_source_line,
                )
            else:
                # No synced lyrics or no lyrics at all - still render for progress bar
                renderer.render(
                    f"{ti.artist} - {ti.title}",
                    timed_lines,
                    current_idx=-1,
                    context_lines=cfg.context_lines,
                    scroll_offset=lyrics_scroll_offset,
                    artist=ti.artist,
                    album=ti.album or "",
                    click_highlight_idx=click_highlight_idx,
                    hover_highlight_idx=hover_highlight_idx,
                    status_notice=status_notice,
                    lyrics_source_line=lyrics_source_line,
                )

            # Check for mouse actions after rendering
            if mouse_handler is not None:
                cols, rows = shutil.get_terminal_size(fallback=(80, 24))
                layout = _compute_layout_info(
                    cols,
                    rows,
                    render_options,
                    has_progress_line=bool(render_options.show_progress_bar and ti.length_ms > 0),
                    lyrics_footer_lines=1 if lyrics_source_line else 0,
                )
                # Drain queued events each tick so press/release pairs don't "stall" controls.
                for _ in range(20):
                    event = mouse_handler.get_event()
                    if not event:
                        break
                    x = int(event.get("x", -1))
                    y = int(event.get("y", -1))
                    is_wheel = bool(event.get("is_wheel"))
                    is_motion = bool(event.get("is_motion"))
                    is_release = bool(event.get("is_release"))
                    button = int(event.get("button", -1))

                    if is_wheel:
                        direction = int(event.get("wheel_direction", 0))
                        if direction < 0:
                            lyrics_scroll_offset = _clamp_scroll_offset(
                                scroll_offset=lyrics_scroll_offset - 1,
                                current_idx=render_current_idx,
                                context_lines=cfg.context_lines,
                                total_lines=len(timed_lines),
                            )
                            last_scroll_action_at = time.monotonic()
                        elif direction > 0:
                            lyrics_scroll_offset = _clamp_scroll_offset(
                                scroll_offset=lyrics_scroll_offset + 1,
                                current_idx=render_current_idx,
                                context_lines=cfg.context_lines,
                                total_lines=len(timed_lines),
                            )
                            last_scroll_action_at = time.monotonic()
                    elif is_motion:
                        lyrics_row_start = layout["lyrics_row_start"]
                        lyrics_row_end = layout["lyrics_row_end"]
                        body_rows = int(layout["body_rows"] or 1)
                        if (
                            lyrics_row_start is not None
                            and lyrics_row_end is not None
                            and lyrics_row_start <= y <= lyrics_row_end
                        ):
                            visible_map = _visible_lyrics_mapping(
                                lines=timed_lines,
                                current_idx=render_current_idx,
                                context_lines=cfg.context_lines,
                                scroll_offset=lyrics_scroll_offset,
                                max_text_width=max(1, cols - 4),
                                body_rows=body_rows,
                            )
                            hovered_wrapped_idx = y - lyrics_row_start
                            if 0 <= hovered_wrapped_idx < len(visible_map):
                                new_hover_idx = visible_map[hovered_wrapped_idx]
                                if new_hover_idx != hover_highlight_idx:
                                    hover_highlight_idx = new_hover_idx
                                    hover_highlight_since = time.monotonic()
                            else:
                                hover_highlight_idx = None
                                hover_highlight_since = None
                        else:
                            hover_highlight_idx = None
                            hover_highlight_since = None
                    elif button == 0 and not is_release:
                        # Click on progress bar: seek by horizontal position
                        progress_row = layout["progress_row"]
                        if (
                            progress_row is not None
                            and y == progress_row
                            and ti.length_ms > 0
                            and cols > 3
                        ):
                            bounds = _progress_bar_click_bounds(
                                cols=cols,
                                current_s=renderer.current_position,
                                total_s=renderer.total_duration,
                                is_playing=renderer.is_playing,
                            )
                            if bounds is not None:
                                bar_left, bar_right = bounds
                                clamped_x = max(bar_left, min(x, bar_right))
                                ratio = (clamped_x - bar_left) / max(1, bar_right - bar_left)
                                target_ms = int(ti.length_ms * ratio)
                                try:
                                    await mpris_async.seek_ms(active_player_name, target_ms)
                                except Exception:
                                    logger.exception("Failed to seek from progress bar click")
                        else:
                            # Click on media controls row
                            controls_row = layout["controls_row"]
                            if (
                                media_controls_enabled
                                and controls_row is not None
                                and y == controls_row
                                and cols > 10
                            ):
                                controls_col_start = 2
                                inner_width, btn_widths = media_controls_layout(cols, 3)
                                rel_x = x - controls_col_start
                                if 0 <= rel_x < inner_width:
                                    boundary = 0
                                    actions = ["prev", "play_pause", "next"]
                                    for btn_idx, width in enumerate(btn_widths):
                                        boundary += width
                                        if rel_x < boundary:
                                            await _handle_mouse_action(
                                                actions[btn_idx], active_player_name
                                            )
                                            break

                            # Click on visualizer area: cycle style and persist config.
                            top_visualizer_start = layout["top_visualizer_start"]
                            top_visualizer_end = layout["top_visualizer_end"]
                            bottom_visualizer_start = layout["bottom_visualizer_start"]
                            bottom_visualizer_end = layout["bottom_visualizer_end"]
                            in_top_visualizer = (
                                top_visualizer_start is not None
                                and top_visualizer_end is not None
                                and top_visualizer_start <= y <= top_visualizer_end
                            )
                            in_bottom_visualizer = (
                                bottom_visualizer_start is not None
                                and bottom_visualizer_end is not None
                                and bottom_visualizer_start <= y <= bottom_visualizer_end
                            )
                            if render_options.show_visualizer and (
                                in_top_visualizer or in_bottom_visualizer
                            ):
                                new_style = _next_visualizer_style(render_options.visualizer_style)
                                render_options.visualizer_style = new_style
                                if renderer.visualizer is not None:
                                    renderer.visualizer.style = new_style
                                try:
                                    save_visual_config(
                                        replace(cfg.visual, visualizer_style=new_style)
                                    )
                                    logger.debug("Visualizer style changed by click: %s", new_style)
                                    status_notice = f"Visualizer: {new_style}"
                                    status_notice_until = time.monotonic() + 2.0
                                except Exception:
                                    logger.exception("Failed to persist visualizer style to config")

                            # Click on lyrics row: seek to that lyric timestamp
                            lyrics_row_start = layout["lyrics_row_start"]
                            lyrics_row_end = layout["lyrics_row_end"]
                            body_rows = int(layout["body_rows"] or 1)
                            if (
                                tracker is not None
                                and timed_line_times_ms
                                and lyrics_row_start is not None
                                and lyrics_row_end is not None
                                and lyrics_row_start <= y <= lyrics_row_end
                            ):
                                visible_map = _visible_lyrics_mapping(
                                    lines=timed_lines,
                                    current_idx=render_current_idx,
                                    context_lines=cfg.context_lines,
                                    scroll_offset=lyrics_scroll_offset,
                                    max_text_width=max(1, cols - 4),
                                    body_rows=body_rows,
                                )
                                clicked_wrapped_idx = y - lyrics_row_start
                                if 0 <= clicked_wrapped_idx < len(visible_map):
                                    target_line_idx = visible_map[clicked_wrapped_idx]
                                    if 0 <= target_line_idx < len(timed_line_times_ms):
                                        target_ms = timed_line_times_ms[target_line_idx]
                                        try:
                                            await mpris_async.seek_ms(active_player_name, target_ms)
                                            lyrics_scroll_offset = 0
                                            last_scroll_action_at = None
                                            click_highlight_idx = target_line_idx
                                            click_highlight_until = time.monotonic() + 1.2
                                        except Exception:
                                            logger.exception("Failed to seek from lyric line click")

             # Restore default auto-follow view after wheel inactivity (smoothly)
            if (
                 hover_highlight_idx is not None
                 and hover_highlight_since is not None
                 and time.monotonic() - hover_highlight_since >= 2.0
             ):
                 hover_highlight_idx = None
                 hover_highlight_since = None

            if (
                 lyrics_scroll_offset != 0
                 and last_scroll_action_at is not None
                 and time.monotonic() - last_scroll_action_at >= 5.0
             ):
                 # Easing: faster far from target, slower near zero.
                 step = max(1, math.ceil(abs(lyrics_scroll_offset) * 0.25))
                 if lyrics_scroll_offset > 0:
                     lyrics_scroll_offset = max(0, lyrics_scroll_offset - step)
                 else:
                     lyrics_scroll_offset = min(0, lyrics_scroll_offset + step)
                 if lyrics_scroll_offset == 0:
                     last_scroll_action_at = None

             # Check for WebSocket lyrics updates
            if lyrics_update_event.is_set():
                 lyrics_update_event.clear()
                 if (
                     new_lyrics_key
                     and new_lyrics_text
                     and new_lyrics_key.artist == ti.artist
                     and new_lyrics_key.title == ti.title
                 ):
                     # Update lyrics for current track
                     lyrics_source_line = format_lyrics_source_footer("local_ingest")
                     doc = parse_lrc(new_lyrics_text)
                     if doc.events:
                         tracker = LineTracker.from_events(doc.events)
                         timed_lines = [e.text for e in doc.events]
                         timed_line_times_ms = [e.t_ms for e in doc.events]
                     else:
                         plain_lines = [ln.rstrip() for ln in new_lyrics_text.splitlines()]
                         timed_lines = plain_lines
                         timed_line_times_ms = []
                         tracker = None
                     # Reset scroll and highlights
                     lyrics_scroll_offset = 0
                     last_scroll_action_at = None
                     click_highlight_idx = None
                     click_highlight_until = None
                     hover_highlight_idx = None
                     hover_highlight_since = None
                     status_notice = None
                     status_notice_until = time.monotonic() + 3.0
                     logger.debug("Lyrics updated for current track %s from WebSocket", ti.title)

            await asyncio.sleep(tick_s)
    finally:
        if ingest_site is not None:
            try:
                await ingest_site.stop()
            except Exception:
                logger.exception("Failed to stop lyrics ingest site")
        if ingest_runner is not None:
            try:
                await ingest_runner.cleanup()
            except Exception:
                logger.exception("Failed to clean up lyrics ingest runner")
        mpris_async.shutdown_mpris_executor()
        if mouse_handler:
            mouse_handler.exit()
        renderer.exit()
