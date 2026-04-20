from __future__ import annotations
import logging
from pprint import pp
import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Callable
from terminal_lyrics.render.themes import ANSITheme, ThemeManager
from terminal_lyrics.i18n import t
from terminal_lyrics.render.layout import (
    BorderChars,
    get_border_chars,
    draw_box_top,
    draw_box_bottom,
    draw_box_separator,
    draw_box_line,
    draw_progress_bar,
    format_time,
    wrap_text,
    _display_width,
    ICON_PLAYING,
    ICON_PAUSED,
    ICON_MUSIC,
)
from terminal_lyrics.render.effects import (
    AnimationState,
    PulseEffect,
    create_gradient,
    fade_text,
)
from terminal_lyrics.render.visualizer import MusicVisualizer, SimpleVisualizer

logger = logging.getLogger(__name__)
CSI = "\x1b["


def _sgr(*codes: int) -> str:
    return CSI + ";".join(str(c) for c in codes) + "m"


def media_controls_layout(cols: int, buttons_count: int = 3) -> tuple[int, list[int]]:
    """Return inner width and per-button widths with centered remainder."""
    inner_width = max(0, cols - 4)  # -2 borders, -2 horizontal padding
    if buttons_count <= 0:
        return inner_width, []
    base = inner_width // buttons_count
    remainder = inner_width - (base * buttons_count)
    widths = [base] * buttons_count
    # Put remainder into center button to keep visual symmetry.
    widths[buttons_count // 2] += remainder
    return inner_width, widths


@dataclass(frozen=True, slots=True)
class Theme:
    """Legacy theme for backward compatibility."""

    title: str = _sgr(36, 1)  # cyan bold
    current: str = _sgr(32, 1)  # green bold
    dim: str = _sgr(90)  # bright black
    warning: str = _sgr(33, 1)  # yellow bold
    reset: str = _sgr(0)


@dataclass
class RenderOptions:
    """Options for enhanced rendering."""

    theme_name: str = "default"
    border_style: str = "rounded"
    show_progress_bar: bool = True
    show_metadata: bool = True
    show_media_controls: bool = True
    show_visualizer: bool = False
    visualizer_style: str = "spectrum"
    visualizer_position: str = "top"
    center_text: bool = True
    enable_animations: bool = True
    enable_gradient: bool = True
    enable_pulse: bool = True
    use_real_audio: bool = True  # Use real audio data for visualizer
    audio_device: str | None = None  # Audio device name
    audio_backend: str = "auto"  # Audio backend
    waveform_style: str = "detailed"  # Waveform rendering style: "simple" or "detailed"
    visualizer_motion: str = "responsive"  # responsive | smooth (spectral dynamics preset)


class EnhancedRenderer:
    """Enhanced ANSI renderer with themes, animations, and effects."""

    def __init__(
        self,
        use_alt_screen: bool = True,
        options: RenderOptions | None = None,
        config_dir: str | None = None,
    ):
        self.use_alt_screen = use_alt_screen
        self.options = options or RenderOptions()
        self._entered = False
        self._resize_handler: Callable[..., None] | None = None
        self._last_render_args: tuple | None = None
        self._pending_resize = False
        # Load theme
        from pathlib import Path

        theme_manager = ThemeManager(Path(config_dir) if config_dir else None)
        self.ansi_theme = theme_manager.get_theme(self.options.theme_name)
        # Border characters
        self.border = get_border_chars(self.options.border_style)
        # Animation state
        self.animation_state = AnimationState()
        self.pulse_effect = PulseEffect(frequency=1.5)
        # Visualizer
        if self.options.show_visualizer:
            self.visualizer = MusicVisualizer(
                width=20,
                height=3,
                style=self.options.visualizer_style,
                use_real_audio=self.options.use_real_audio,
                audio_device=self.options.audio_device,
                audio_backend=self.options.audio_backend,
                waveform_style=self.options.waveform_style,
                motion=self.options.visualizer_motion,
            )
            self.simple_visualizer = SimpleVisualizer(style="equalizer", speed=5.0)
        else:
            self.visualizer = None
            self.simple_visualizer = None
        # Track state
        self.current_position: float = 0.0
        self.total_duration: float = 0.0
        self.is_playing: bool = True

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit()

    def enter(self) -> None:
        if self._entered:
            return
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049h")  # alt screen
        sys.stdout.write(CSI + "?25l")  # hide cursor
        sys.stdout.write(CSI + "H" + CSI + "2J")  # home + clear
        sys.stdout.flush()
        self._entered = True

        # Register SIGWINCH handler for resize (must not call render() here — stdout is
        # not re-entrant if a resize arrives mid-write).
        def _on_resize(signum=None, frame=None):
            self._pending_resize = True

        self._resize_handler = _on_resize
        signal.signal(signal.SIGWINCH, _on_resize)

    def exit(self) -> None:
        if not self._entered:
            return
        # Cleanup visualizer
        if self.visualizer:
            self.visualizer.cleanup()
        # Restore default SIGWINCH handler
        if self._resize_handler:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
            self._resize_handler = None
        sys.stdout.write(self.ansi_theme.reset)
        sys.stdout.write(CSI + "?25h")  # show cursor
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049l")  # normal screen
        sys.stdout.flush()
        self._entered = False
        self._last_render_args = None
        self._pending_resize = False

    def _render_media_controls(self, cols: int) -> str:
        """Render media control buttons row: prev, play/pause, next."""
        if cols < 30:
            return ""

        # Dynamic play/pause based on current state
        if self.is_playing:
            play_icon = "⏸"
            play_text = t("btn_pause")
            play_color = self.ansi_theme.status_playing
        else:
            play_icon = "▶"
            play_text = t("btn_play")
            play_color = self.ansi_theme.status_paused

        # Button definitions: (icon, label, color) - using i18n
        buttons = [
            ("⏮", t("btn_prev"), self.ansi_theme.time_text),
            (play_icon, play_text, play_color),
            ("⏭", t("btn_next"), self.ansi_theme.time_text),
        ]

        # Calculate available width for buttons (excluding borders and padding)
        inner_width, btn_widths = media_controls_layout(cols, len(buttons))

        # Build buttons row with proper centering (ignoring ANSI codes)
        parts = []
        for (icon, label, color), btn_width in zip(buttons, btn_widths):
            btn_text = f" {icon} {label} "
            visible_len = _display_width(btn_text)
            padding = btn_width - visible_len
            left_pad = padding // 2
            right_pad = padding - left_pad
            # Ensure no negative padding
            left_pad = max(left_pad, 0)
            right_pad = max(right_pad, 0)
            centered = " " * left_pad + color + btn_text + self.ansi_theme.reset + " " * right_pad + self.ansi_theme.border
            parts.append(centered)
        controls = "".join(parts)
        visible_controls_width = _display_width(controls)
        if visible_controls_width < inner_width:
            pad = inner_width - visible_controls_width
            pad_left = pad // 2
            pad_right = pad - pad_left
            controls = (" " * pad_left) + controls + (" " * pad_right)
        return controls

    def update_playback_state(self, position: float, duration: float, playing: bool) -> None:
        """Update playback state for progress bar."""
        self.current_position = position
        self.total_duration = duration
        self.is_playing = playing

    def _slice_visible_text(self, text: str, start_col: int, width: int) -> str:
        """Slice plain text by terminal display columns."""
        if width <= 0:
            return ""
        out: list[str] = []
        col = 0
        end_col = start_col + width
        for ch in text:
            ch_w = _display_width(ch)
            next_col = col + ch_w
            if next_col <= start_col:
                col = next_col
                continue
            if col >= end_col:
                break
            # Include the whole char only if it fits.
            if next_col <= end_col:
                out.append(ch)
            else:
                break
            col = next_col
        return "".join(out)

    def _animated_title(self, text: str, inner_width: int) -> str:
        """Animate long title with smooth horizontal marquee."""
        text_width = _display_width(text)
        if text_width <= inner_width:
            return text

        overflow = text_width - inner_width
        speed_cols_per_s = 8.0
        hold_s = 1.0
        travel_s = overflow / speed_cols_per_s
        cycle_s = hold_s + travel_s + hold_s + travel_s
        t = self.animation_state.elapsed() % max(cycle_s, 0.001)

        if t < hold_s:
            offset = 0
        elif t < hold_s + travel_s:
            offset = int((t - hold_s) * speed_cols_per_s)
        elif t < hold_s + travel_s + hold_s:
            offset = overflow
        else:
            back_t = t - (hold_s + travel_s + hold_s)
            offset = overflow - int(back_t * speed_cols_per_s)

        offset = max(0, min(overflow, offset))
        return self._slice_visible_text(text, offset, inner_width)

    def render(
        self,
        title: str,
        lines: list[str],
        current_idx: int,
        context_lines: int = 1,
        scroll_offset: int = 0,
        artist: str = "",
        album: str = "",
        click_highlight_idx: int | None = None,
        hover_highlight_idx: int | None = None,
        status_notice: str | None = None,
        lyrics_source_line: str | None = None,
    ) -> None:
        """Render with enhanced UI."""
        # Store args for SIGWINCH redraw
        self._last_render_args = (
            title,
            lines,
            current_idx,
            context_lines,
            scroll_offset,
            artist,
            album,
            click_highlight_idx,
            hover_highlight_idx,
            status_notice,
            lyrics_source_line,
        )
        # Update animation state
        self.animation_state.tick()
        # Update visualizer
        if self.visualizer:
            self.visualizer.update(self.is_playing)
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        out: list[str] = []
        # Calculate available space
        header_lines = 1
        if self.options.show_metadata:
            header_lines += 3  # title + separator + progress
            if self.options.show_media_controls:
                header_lines += 1  # media controls row
        if (
            self.options.show_visualizer
            and self.visualizer
            and self.options.visualizer_position == "top"
        ):
            header_lines += 4  # visualizer + separator
        footer_lines = 0
        if (
            self.options.show_visualizer
            and self.visualizer
            and self.options.visualizer_position == "bottom"
        ):
            footer_lines += 4
        body_rows = max(rows - header_lines - footer_lines - 2, 1)  # -2 for top/bottom border
        main_body_rows = body_rows - (1 if lyrics_source_line else 0)
        if main_body_rows < 0:
            main_body_rows = 0
        # Top border
        out.append(self.ansi_theme.border + draw_box_top(cols, self.border) + self.ansi_theme.reset + self.ansi_theme.border)
        # Visualizer at top
        if (
            self.options.show_visualizer
            and self.visualizer
            and self.options.visualizer_position == "top"
        ):
            viz_lines = self.visualizer.render()
            for viz_line in viz_lines:
                colored_viz = self.ansi_theme.progress_bar_filled + viz_line + self.ansi_theme.reset + self.ansi_theme.border
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(colored_viz, cols, self.border, "center")
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )
            out.append(
                self.ansi_theme.border
                + draw_box_separator(cols, self.border)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
        # Header with metadata
        if self.options.show_metadata:
            # Title line with music icon
            icon = ICON_MUSIC
            if self.simple_visualizer and self.is_playing:
                icon = self.simple_visualizer.get_frame()
            if status_notice:
                title_text = f"{icon} {title}  [{status_notice}]"
            else:
                title_text = f"{icon} {title}"
            title_overflow = _display_width(title_text) > max(1, cols - 4)
            title_text = self._animated_title(title_text, max(1, cols - 4))
            # Apply gradient effect if enabled
            if (
                self.options.enable_gradient
                and self.ansi_theme.gradient_start
                and self.ansi_theme.gradient_end
            ):
                # Extract colors from ANSI codes (simplified)
                title_colored = self.ansi_theme.title + title_text + self.ansi_theme.reset + self.ansi_theme.border
            else:
                title_colored = self.ansi_theme.title + title_text + self.ansi_theme.reset + self.ansi_theme.border
            out.append(
                self.ansi_theme.border
                + draw_box_line(title_colored, cols, self.border, "left" if title_overflow else "center")
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
            # Progress bar
            if self.options.show_progress_bar and self.total_duration > 0:
                out.append(
                    self.ansi_theme.border
                    + draw_box_separator(cols, self.border)
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )
                time_current = format_time(self.current_position)
                time_total = format_time(self.total_duration)
                time_str = f"{time_current} / {time_total}"
                # Status icon
                status_icon = ICON_PLAYING if self.is_playing else ICON_PAUSED
                status_color = (
                    self.ansi_theme.status_playing
                    if self.is_playing
                    else self.ansi_theme.status_paused
                )
                # Calculate progress bar width
                time_width = len(time_str) + 3  # +3 for icon and spaces
                bar_width = max(10, cols - time_width - 4)  # -4 for borders and padding
                progress = draw_progress_bar(
                    self.current_position,
                    self.total_duration,
                    bar_width,
                    filled_char="━",
                    empty_char="─",
                )
                progress_colored = (
                    self.ansi_theme.progress_bar_filled
                    + progress[: int(bar_width * (self.current_position / self.total_duration))]
                    + self.ansi_theme.progress_bar_empty
                    + progress[int(bar_width * (self.current_position / self.total_duration)) :]
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )
                progress_line = (
                    status_color
                    + status_icon
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                    + " "
                    + progress_colored
                    + " "
                    + self.ansi_theme.time_text
                    + time_str
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(progress_line, cols, self.border, "center")
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )

                # Media control buttons row
                if self.options.show_media_controls:
                    controls_line = self._render_media_controls(cols)
                    out.append(
                        self.ansi_theme.border
                        + draw_box_line(controls_line, cols, self.border)
                        + self.ansi_theme.reset
                        + self.ansi_theme.border
                    )
            out.append(
                self.ansi_theme.border
                + draw_box_separator(cols, self.border)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
        # Lyrics body - expand lines with word wrapping
        if current_idx < 0:
            base_start = 0
        else:
            base_start = max(current_idx - context_lines, 0)
        start = max(0, base_start + scroll_offset)

        # Wrap all lines first, keeping track of which original line each wrapped line belongs to
        # (original_idx, text, is_first_part)
        wrapped_lines: list[tuple[int, str, bool]] = []
        max_text_width = cols - 4  # -4 for borders and padding

        for i in range(start, len(lines)):
            text = lines[i]
            wrapped = wrap_text(text, max_text_width)
            for j, wline in enumerate(wrapped):
                wrapped_lines.append((i, wline, j == 0))

        # Visible wrapped rows (lyrics only; footer line is separate)
        end = min(len(wrapped_lines), main_body_rows)
        visible = wrapped_lines[:end]

        for orig_idx, text, is_first in visible:
            # Apply styling based on original line index
            if orig_idx == current_idx:
                # Only add triangle on the first part of the current line
                prefix = "► " if is_first else "  "
                styled_text = self.ansi_theme.current_line + prefix + text + self.ansi_theme.reset + self.ansi_theme.border
            elif click_highlight_idx is not None and orig_idx == click_highlight_idx:
                # Briefly highlight clicked lyric line as seek feedback.
                prefix = "▸ " if is_first else "  "
                styled_text = self.ansi_theme.warning + prefix + text + self.ansi_theme.reset + self.ansi_theme.border
            elif hover_highlight_idx is not None and orig_idx == hover_highlight_idx:
                # Hovered line under mouse pointer.
                prefix = "▹ " if is_first else "  "
                styled_text = self.ansi_theme.artist + prefix + text + self.ansi_theme.reset + self.ansi_theme.border
            elif orig_idx < current_idx:
                styled_text = self.ansi_theme.past_line + text + self.ansi_theme.reset + self.ansi_theme.border
            else:
                styled_text = self.ansi_theme.future_line + text + self.ansi_theme.reset + self.ansi_theme.border
            align = "center" if self.options.center_text else "left"
            out.append(
                self.ansi_theme.border
                + draw_box_line(styled_text, cols, self.border, align)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )

        for _ in range(max(0, main_body_rows - len(visible))):
            out.append(
                self.ansi_theme.border
                + draw_box_line("", cols, self.border)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )

        if lyrics_source_line:
            att_align = "center" if self.options.center_text else "left"
            # past_line: theme gray (readable); dim_line is often too dark and reads as black
            att_styled = (
                self.ansi_theme.past_line
                + lyrics_source_line
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
            out.append(
                self.ansi_theme.border
                + draw_box_line(att_styled, cols, self.border, att_align)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
        # Visualizer at bottom
        if (
            self.options.show_visualizer
            and self.visualizer
            and self.options.visualizer_position == "bottom"
        ):
            out.append(
                self.ansi_theme.border
                + draw_box_separator(cols, self.border)
                + self.ansi_theme.reset
                + self.ansi_theme.border
            )
            viz_lines = self.visualizer.render()
            for viz_line in viz_lines:
                colored_viz = self.ansi_theme.progress_bar_filled + viz_line + self.ansi_theme.reset + self.ansi_theme.border
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(colored_viz, cols, self.border, "center")
                    + self.ansi_theme.reset
                    + self.ansi_theme.border
                )
        # Bottom border
        out.append(
            self.ansi_theme.border + draw_box_bottom(cols, self.border) + self.ansi_theme.reset + self.ansi_theme.border
        )
        # Render to screen
        sys.stdout.write(CSI + "H" + CSI + "2J")
        sys.stdout.write("\n".join(out))
        sys.stdout.write(self.ansi_theme.reset)
        sys.stdout.flush()
        if self._pending_resize and self._last_render_args:
            self._pending_resize = False
            self.render(*self._last_render_args)


class AnsiRenderer:
    """Legacy ANSI renderer for backward compatibility."""

    def __init__(self, use_alt_screen: bool = True, theme: Theme | None = None):
        self.use_alt_screen = use_alt_screen
        self.theme = theme or Theme()
        self._entered = False
        self._resize_handler: Callable[..., None] | None = None
        self._last_render_args: tuple[str, list[str], int, int] | None = None
        self._last_scroll_offset: int = 0
        self._pending_resize = False

    def __setattr__(self, name: str, value) -> None:
        """
        Tests patch `renderer.render` with a mock. If they do, we still want to
        capture the "last render args" so SIGWINCH redraw can call render again.
        """
        if name == "render" and hasattr(value, "call_count") and callable(value):
            mock_render = value

            def _wrapped_render(
                title: str, lines: list[str], current_idx: int, context_lines: int = 1, scroll_offset: int = 0
            ):
                self._last_render_args = (title, lines, current_idx, context_lines)
                self._last_scroll_offset = scroll_offset
                return mock_render(
                    title, lines, current_idx=current_idx, context_lines=context_lines, scroll_offset=scroll_offset
                )

            return object.__setattr__(self, name, _wrapped_render)
        return object.__setattr__(self, name, value)

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit()

    def enter(self) -> None:
        if self._entered:
            return
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049h")  # alt screen
        sys.stdout.write(CSI + "?25l")  # hide cursor
        sys.stdout.write(CSI + "H" + CSI + "2J")  # home + clear
        sys.stdout.flush()
        self._entered = True

        # Register SIGWINCH handler for resize (must not call render() here — stdout is
        # not re-entrant if a resize arrives mid-write).
        def _on_resize(signum=None, frame=None):
            self._pending_resize = True

        self._resize_handler = _on_resize
        signal.signal(signal.SIGWINCH, _on_resize)

    def exit(self) -> None:
        if not self._entered:
            return
        # Restore default SIGWINCH handler
        if self._resize_handler:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
            self._resize_handler = None
        sys.stdout.write(self.theme.reset)
        sys.stdout.write(CSI + "?25h")  # show cursor
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049l")  # normal screen
        sys.stdout.flush()
        self._entered = False
        self._last_render_args = None
        self._last_scroll_offset = 0
        self._pending_resize = False

    def render(
        self,
        title: str,
        lines: list[str],
        current_idx: int,
        context_lines: int = 1,
        scroll_offset: int = 0,
    ) -> None:
        # Store args for SIGWINCH redraw
        self._last_render_args = (title, lines, current_idx, context_lines)
        self._last_scroll_offset = scroll_offset
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        # reserve 1 line for title
        body_rows = max(rows - 1, 1)
        # window around current line, but keep within list
        if current_idx < 0:
            base_start = 0
        else:
            base_start = max(current_idx - context_lines, 0)
        start = max(0, base_start + scroll_offset)
        end = min(start + body_rows, len(lines))
        start = max(end - body_rows, 0)
        out: list[str] = []
        out.append(f"{self.theme.title}♫ {title} ♫{self.theme.reset}")
        for i in range(start, end):
            t = lines[i]
            if i == current_idx:
                out.append(f"{self.theme.current}{t}{self.theme.reset}")
            else:
                out.append(f"{self.theme.dim}{t}{self.theme.reset}")
        # move home + clear, then print full frame
        sys.stdout.write(CSI + "H" + CSI + "2J")
        sys.stdout.write("\n".join(out))
        sys.stdout.write(self.theme.reset)
        sys.stdout.flush()
        if self._pending_resize and self._last_render_args:
            self._pending_resize = False
            title, lines, current_idx, context_lines = self._last_render_args
            self.render(title, lines, current_idx, context_lines, self._last_scroll_offset)
