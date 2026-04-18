"""Interactive TUI setup menu with live theme/visualizer preview."""

from __future__ import annotations

import select
import shutil
import sys
import termios
import tty
import os
from dataclasses import dataclass
from typing import Literal

from terminal_lyrics.config import AudioConfig, VisualConfig
from terminal_lyrics.i18n import t
from terminal_lyrics.render.layout import (
    ICON_MUSIC,
    draw_box_bottom,
    draw_box_line,
    draw_box_separator,
    draw_box_top,
    draw_progress_bar,
    format_time,
    get_border_chars,
)
from terminal_lyrics.render.themes import ANSITheme, ThemeManager
from terminal_lyrics.render.visualizer import MusicVisualizer, VisualizerMotion

CSI = "\x1b["

BorderStyle = Literal["rounded", "double", "single", "heavy", "ascii"]
VisualizerStyle = Literal["equalizer", "waveform", "blocks", "dots", "centered"]


@dataclass
class WizardState:
    """Mutable setup state mirrored from config."""

    lang: str
    theme: str
    border_style: BorderStyle
    show_progress_bar: bool
    show_visualizer: bool
    visualizer_style: VisualizerStyle
    visualizer_motion: VisualizerMotion
    center_text: bool
    enable_animations: bool
    enable_mouse: bool
    enable_media_controls: bool
    audio_backend: str
    use_real_audio: bool

    @classmethod
    def from_config(cls, cfg) -> "WizardState":
        return cls(
            lang=cfg.lang,
            theme=cfg.visual.theme,
            border_style=cfg.visual.border_style,
            show_progress_bar=cfg.visual.show_progress_bar,
            show_visualizer=cfg.visual.show_visualizer,
            visualizer_style=cfg.visual.visualizer_style,
            visualizer_motion=cfg.visual.visualizer_motion,
            center_text=cfg.visual.center_text,
            enable_animations=cfg.visual.enable_animations,
            enable_mouse=cfg.enable_mouse,
            enable_media_controls=cfg.enable_media_controls,
            audio_backend=cfg.audio.audio_backend,
            use_real_audio=cfg.audio.use_real_audio,
        )

    def to_visual_config(self, current_visual: VisualConfig) -> VisualConfig:
        return VisualConfig(
            theme=self.theme,
            border_style=self.border_style,
            show_progress_bar=self.show_progress_bar,
            show_metadata=current_visual.show_metadata,
            show_visualizer=self.show_visualizer,
            visualizer_style=self.visualizer_style,
            visualizer_motion=self.visualizer_motion,
            visualizer_position=current_visual.visualizer_position,
            center_text=self.center_text,
            enable_animations=self.enable_animations,
            enable_gradient=current_visual.enable_gradient,
            enable_pulse=current_visual.enable_pulse,
        )

    def to_audio_config(self, current_audio: AudioConfig) -> AudioConfig:
        return AudioConfig(
            audio_device=current_audio.audio_device,
            audio_backend=self.audio_backend,
            use_real_audio=self.use_real_audio,
        )


@dataclass(frozen=True)
class MenuItem:
    key: str
    title_key: str
    kind: Literal["cycle", "toggle", "action"]
    values: tuple[str, ...] = ()
    on_label: str = "ON"
    off_label: str = "OFF"


def _read_key(timeout: float = 0.1) -> str | None:
    """Read single key (supports arrows)."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None

    ch = os.read(sys.stdin.fileno(), 1).decode("latin-1", errors="ignore")
    if ch != "\x1b":
        return ch

    # Gather the rest of an escape sequence (arrow keys, etc.)
    seq = ch
    for _ in range(4):
        ready, _, _ = select.select([sys.stdin], [], [], 0.02)
        if not ready:
            break
        seq += os.read(sys.stdin.fileno(), 1).decode("latin-1", errors="ignore")

    mapping = {
        "\x1b[A": "up",
        "\x1b[B": "down",
        "\x1b[C": "right",
        "\x1b[D": "left",
        "\x1bOA": "up",    # application cursor mode
        "\x1bOB": "down",
        "\x1bOC": "right",
        "\x1bOD": "left",
    }
    if seq in mapping:
        return mapping[seq]

    # Treat unknown escape sequences as no-op; do not quit.
    if seq == "\x1b":
        return "esc"
    return None


def _cycle_value(values: tuple[str, ...], current: str, direction: int) -> str:
    if not values:
        return current
    try:
        idx = values.index(current)
    except ValueError:
        idx = 0
    return values[(idx + direction) % len(values)]


def _status_for(item: MenuItem, state: WizardState) -> str:
    value = getattr(state, item.key, "")
    if item.kind == "toggle":
        return item.on_label if bool(value) else item.off_label
    if item.kind == "cycle":
        if item.key == "visualizer_motion":
            return t(f"visualizer_motion_{value}")
        return str(value)
    return ""


def _apply_change(item: MenuItem, state: WizardState, direction: int) -> None:
    if item.kind == "toggle":
        setattr(state, item.key, not bool(getattr(state, item.key)))
        return
    if item.kind == "cycle":
        current = str(getattr(state, item.key))
        setattr(state, item.key, _cycle_value(item.values, current, direction))


def _fit_text(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def _preview_lines(theme: ANSITheme, state: WizardState, width: int, now_s: float = 87.0) -> list[str]:
    border = get_border_chars(state.border_style)
    lines: list[str] = []
    lines.append(theme.border + draw_box_top(width, border) + theme.reset)

    if state.show_visualizer:
        visualizer = MusicVisualizer(
            # Keep preview parameters aligned with EnhancedRenderer.
            width=20,
            height=5,
            style=state.visualizer_style,
            use_real_audio=False,
            waveform_style="detailed",
            motion=state.visualizer_motion,
        )
        try:
            # Warm up several ticks to make preview more expressive immediately.
            for _ in range(4):
                visualizer.update(True)

            viz_lines = visualizer.render()
            total_viz_rows = max(1, len(viz_lines))
            for row_idx, vline in enumerate(viz_lines):
                # Top rows brighter, lower rows softer for better depth perception.
                if row_idx < total_viz_rows // 3:
                    row_color = theme.status_playing
                elif row_idx < (2 * total_viz_rows) // 3:
                    row_color = theme.progress_bar_filled
                else:
                    row_color = theme.time_text
                colored = row_color + vline + theme.reset
                lines.append(theme.border + draw_box_line(colored, width, border, "center") + theme.reset)
                
        finally:
            visualizer.cleanup()
    lines.append(theme.border + draw_box_separator(width, border) + theme.reset)
    title = f"{theme.title}{ICON_MUSIC} {t('wizard_preview_title')}{theme.reset}"
    lines.append(theme.border + draw_box_line(title, width, border, "center") + theme.reset)
    lines.append(theme.border + draw_box_separator(width, border) + theme.reset)

    if state.show_progress_bar:
        total_s = 213.0
        time_str = f"{format_time(now_s)} / {format_time(total_s)}"
        bar_width = max(8, width - len(time_str) - 8)
        bar = draw_progress_bar(now_s, total_s, bar_width, filled_char="━", empty_char="─")
        ratio = 0.0 if total_s <= 0 else max(0.0, min(1.0, now_s / total_s))
        split = int(len(bar) * ratio)
        bar_colored = (
            theme.progress_bar_filled + bar[:split] + theme.progress_bar_empty + bar[split:] + theme.reset
        )
        progress_line = f"{bar_colored} {theme.time_text}{time_str}{theme.reset}"
        lines.append(theme.border + draw_box_line(progress_line, width, border, "center") + theme.reset)
        lines.append(theme.border + draw_box_separator(width, border) + theme.reset)

    lyrics = [
        theme.past_line + t("wizard_preview_lyric_1") + theme.reset,
        theme.current_line + t("wizard_preview_lyric_2") + theme.reset,
        theme.future_line + t("wizard_preview_lyric_3") + theme.reset,
    ]
    align = "center" if state.center_text else "left"
    for lyric in lyrics:
        lines.append(theme.border + draw_box_line(lyric, width, border, align) + theme.reset)


    lines.append(theme.border + draw_box_bottom(width, border) + theme.reset)
    return lines


def run_setup_tui(cfg, *, theme_manager: ThemeManager) -> tuple[str, VisualConfig, AudioConfig, bool, bool] | None:
    """Run setup menu. Returns new configs or None when cancelled."""
    state = WizardState.from_config(cfg)
    themes = tuple(theme_manager.list_themes())
    on_label = t("wizard_status_on")
    off_label = t("wizard_status_off")
    menu_items = [
        MenuItem("lang", "wizard_menu_language", "cycle", ("EN", "RU")),
        MenuItem("theme", "wizard_menu_theme", "cycle", themes),
        MenuItem(
            "border_style",
            "wizard_menu_border_style",
            "cycle",
            ("rounded", "double", "single", "heavy", "ascii"),
        ),
        MenuItem("show_visualizer", "wizard_menu_visualizer", "toggle", on_label=on_label, off_label=off_label),
        MenuItem(
            "visualizer_style",
            "wizard_menu_visualizer_style",
            "cycle",
            ("equalizer", "waveform", "blocks", "dots", "centered"),
        ),
        MenuItem(
            "visualizer_motion",
            "wizard_menu_visualizer_motion",
            "cycle",
            ("responsive", "smooth"),
        ),
        MenuItem("show_progress_bar", "wizard_menu_progress_bar", "toggle", on_label=on_label, off_label=off_label),
        MenuItem("center_text", "wizard_menu_center_text", "toggle", on_label=on_label, off_label=off_label),
        MenuItem("enable_animations", "wizard_menu_animations", "toggle", on_label=on_label, off_label=off_label),
        MenuItem("enable_mouse", "wizard_menu_mouse_controls", "toggle", on_label=on_label, off_label=off_label),
        MenuItem(
            "enable_media_controls",
            "wizard_menu_media_buttons",
            "toggle",
            on_label=on_label,
            off_label=off_label,
        ),
        MenuItem("audio_backend", "wizard_menu_audio_backend", "cycle", ("auto", "pulsectl", "sounddevice", "pyaudio")),
        MenuItem(
            "use_real_audio",
            "wizard_menu_real_audio_capture",
            "toggle",
            on_label=on_label,
            off_label=off_label,
        ),
        MenuItem("save", "wizard_menu_save_exit", "action"),
        MenuItem("cancel", "wizard_menu_cancel", "action"),
    ]

    selected = 0
    old_term = termios.tcgetattr(sys.stdin.fileno())
    tty.setcbreak(sys.stdin.fileno())
    sys.stdout.write(CSI + "?1049h" + CSI + "?25l")
    sys.stdout.flush()

    try:
        while True:
            cols, rows = shutil.get_terminal_size(fallback=(120, 30))
            cols = max(cols, 80)
            rows = max(rows, 18)
            menu_w = max(34, min(48, cols // 3))
            preview_w = max(30, cols - menu_w - 5)

            theme = theme_manager.get_theme(state.theme)
            preview = _preview_lines(theme, state, preview_w)

            out: list[str] = [CSI + "H" + CSI + "2J"]
            out.append(f"{theme.title}{t('wizard_title')}{theme.reset}")
            out.append(t("wizard_help_keys"))

            max_rows = rows - 4
            for row in range(max_rows):
                left = ""
                if row < len(menu_items):
                    item = menu_items[row]
                    marker = ">" if row == selected else " "
                    status = _status_for(item, state)
                    title = t(item.title_key)
                    if item.kind == "action":
                        line = f"{marker} {title}"
                    else:
                        line = f"{marker} {title:<20} {status}"
                    left = _fit_text(line, menu_w)

                right = preview[row] if row < len(preview) else ""
                out.append(f"{left:<{menu_w}}  {right}")

            sys.stdout.write("\n".join(out))
            sys.stdout.flush()

            key = _read_key(0.12)
            if key is None:
                continue

            if key in ("up", "k"):
                selected = (selected - 1) % len(menu_items)
                continue
            if key in ("down", "j"):
                selected = (selected + 1) % len(menu_items)
                continue

            current = menu_items[selected]
            if key in ("left", "h"):
                _apply_change(current, state, -1)
                continue
            if key in ("right", "l", " ", "\r", "\n"):
                if current.kind == "action":
                    if current.key == "save":
                        visual = state.to_visual_config(cfg.visual)
                        audio = state.to_audio_config(cfg.audio)
                        return state.lang, visual, audio, state.enable_mouse, state.enable_media_controls
                    return None
                _apply_change(current, state, 1)
                continue
            if key in ("s", "S"):
                visual = state.to_visual_config(cfg.visual)
                audio = state.to_audio_config(cfg.audio)
                return state.lang, visual, audio, state.enable_mouse, state.enable_media_controls
            if key in ("q", "Q", "esc"):
                return None
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term)
        sys.stdout.write(CSI + "?25h" + CSI + "?1049l")
        sys.stdout.flush()
