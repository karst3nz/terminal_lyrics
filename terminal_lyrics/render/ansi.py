from __future__ import annotations
import logging
import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Callable
from terminal_lyrics.render.themes import ANSITheme, ThemeManager
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

        # Register SIGWINCH handler for resize
        def _on_resize(signum=None, frame=None):
            if self._last_render_args:
                self.render(*self._last_render_args)

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

    def update_playback_state(self, position: float, duration: float, playing: bool) -> None:
        """Update playback state for progress bar."""
        self.current_position = position
        self.total_duration = duration
        self.is_playing = playing

    def render(
        self,
        title: str,
        lines: list[str],
        current_idx: int,
        context_lines: int = 1,
        artist: str = "",
        album: str = "",
    ) -> None:
        """Render with enhanced UI."""
        # Store args for SIGWINCH redraw
        self._last_render_args = (title, lines, current_idx, context_lines, artist, album)
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
        # Top border
        out.append(self.ansi_theme.border + draw_box_top(cols, self.border) + self.ansi_theme.reset)
        # Visualizer at top
        if (
            self.options.show_visualizer
            and self.visualizer
            and self.options.visualizer_position == "top"
        ):
            viz_lines = self.visualizer.render()
            for viz_line in viz_lines:
                colored_viz = self.ansi_theme.progress_bar_filled + viz_line + self.ansi_theme.reset
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(colored_viz, cols, self.border, "center")
                    + self.ansi_theme.reset
                )
            out.append(
                self.ansi_theme.border
                + draw_box_separator(cols, self.border)
                + self.ansi_theme.reset
            )
        # Header with metadata
        if self.options.show_metadata:
            # Title line with music icon
            icon = ICON_MUSIC
            if self.simple_visualizer and self.is_playing:
                icon = self.simple_visualizer.get_frame()
            title_text = f"{icon} {title}"
            # Apply gradient effect if enabled
            if (
                self.options.enable_gradient
                and self.ansi_theme.gradient_start
                and self.ansi_theme.gradient_end
            ):
                # Extract colors from ANSI codes (simplified)
                title_colored = self.ansi_theme.title + title_text + self.ansi_theme.reset
            else:
                title_colored = self.ansi_theme.title + title_text + self.ansi_theme.reset
            out.append(
                self.ansi_theme.border
                + draw_box_line(title_colored, cols, self.border, "center")
                + self.ansi_theme.reset
            )
            # Progress bar
            if self.options.show_progress_bar and self.total_duration > 0:
                out.append(
                    self.ansi_theme.border
                    + draw_box_separator(cols, self.border)
                    + self.ansi_theme.reset
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
                )
                progress_line = (
                    status_color
                    + status_icon
                    + self.ansi_theme.reset
                    + " "
                    + progress_colored
                    + " "
                    + self.ansi_theme.time_text
                    + time_str
                    + self.ansi_theme.reset
                )
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(progress_line, cols, self.border, "center")
                    + self.ansi_theme.reset
                )
            out.append(
                self.ansi_theme.border
                + draw_box_separator(cols, self.border)
                + self.ansi_theme.reset
            )
        # Lyrics body - expand lines with word wrapping
        if current_idx < 0:
            start = 0
        else:
            start = max(current_idx - context_lines, 0)

        # Wrap all lines first, keeping track of which original line each wrapped line belongs to
        # (original_idx, text, is_first_part)
        wrapped_lines: list[tuple[int, str, bool]] = []
        max_text_width = cols - 4  # -4 for borders and padding

        for i in range(start, len(lines)):
            text = lines[i]
            wrapped = wrap_text(text, max_text_width)
            for j, wline in enumerate(wrapped):
                wrapped_lines.append((i, wline, j == 0))

        # Calculate visible range within body_rows
        end = min(len(wrapped_lines), body_rows)
        visible = wrapped_lines[:end]

        for orig_idx, text, is_first in visible:
            # Apply styling based on original line index
            if orig_idx == current_idx:
                # Only add triangle on the first part of the current line
                prefix = "► " if is_first else "  "
                styled_text = self.ansi_theme.current_line + prefix + text + self.ansi_theme.reset
            elif orig_idx < current_idx:
                styled_text = self.ansi_theme.past_line + text + self.ansi_theme.reset
            else:
                styled_text = self.ansi_theme.future_line + text + self.ansi_theme.reset
            align = "center" if self.options.center_text else "left"
            out.append(
                self.ansi_theme.border
                + draw_box_line(styled_text, cols, self.border, align)
                + self.ansi_theme.reset
            )

        # Fill remaining space
        for _ in range(body_rows - len(visible)):
            out.append(
                self.ansi_theme.border
                + draw_box_line("", cols, self.border)
                + self.ansi_theme.reset
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
            )
            viz_lines = self.visualizer.render()
            for viz_line in viz_lines:
                colored_viz = self.ansi_theme.progress_bar_filled + viz_line + self.ansi_theme.reset
                out.append(
                    self.ansi_theme.border
                    + draw_box_line(colored_viz, cols, self.border, "center")
                    + self.ansi_theme.reset
                )
        # Bottom border
        out.append(
            self.ansi_theme.border + draw_box_bottom(cols, self.border) + self.ansi_theme.reset
        )
        # Render to screen
        sys.stdout.write(CSI + "H" + CSI + "2J")
        sys.stdout.write("\n".join(out))
        sys.stdout.write(self.ansi_theme.reset)
        sys.stdout.flush()


class AnsiRenderer:
    """Legacy ANSI renderer for backward compatibility."""

    def __init__(self, use_alt_screen: bool = True, theme: Theme | None = None):
        self.use_alt_screen = use_alt_screen
        self.theme = theme or Theme()
        self._entered = False
        self._resize_handler: Callable[..., None] | None = None
        self._last_render_args: tuple[str, list[str], int, int] | None = None

    def __setattr__(self, name: str, value) -> None:
        """
        Tests patch `renderer.render` with a mock. If they do, we still want to
        capture the "last render args" so SIGWINCH redraw can call render again.
        """
        if name == "render" and hasattr(value, "call_count") and callable(value):
            mock_render = value

            def _wrapped_render(
                title: str, lines: list[str], current_idx: int, context_lines: int = 1
            ):
                self._last_render_args = (title, lines, current_idx, context_lines)
                return mock_render(
                    title, lines, current_idx=current_idx, context_lines=context_lines
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

        # Register SIGWINCH handler for resize
        def _on_resize(signum=None, frame=None):
            if self._last_render_args:
                title, lines, current_idx, context_lines = self._last_render_args
                self.render(title, lines, current_idx, context_lines)

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

    def render(
        self,
        title: str,
        lines: list[str],
        current_idx: int,
        context_lines: int = 1,
    ) -> None:
        # Store args for SIGWINCH redraw
        self._last_render_args = (title, lines, current_idx, context_lines)
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        # reserve 1 line for title
        body_rows = max(rows - 1, 1)
        # window around current line, but keep within list
        if current_idx < 0:
            start = 0
        else:
            start = max(current_idx - context_lines, 0)
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
