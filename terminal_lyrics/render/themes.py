from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _rgb_to_ansi(r: int, g: int, b: int, bg: bool = False) -> str:
    """Convert RGB to ANSI 24-bit color code."""
    code = 48 if bg else 38
    return f"\x1b[{code};2;{r};{g};{b}m"


def _ansi_256(color: int, bg: bool = False) -> str:
    """Convert 256-color palette index to ANSI code."""
    code = 48 if bg else 38
    return f"\x1b[{code};5;{color}m"


def _parse_color(color: str | int, bg: bool = False) -> str:
    """
    Parse color from various formats:
    - Hex: "#RRGGBB" or "#RGB"
    - RGB tuple string: "rgb(R, G, B)"
    - 256-color index: integer 0-255
    - ANSI code: raw escape sequence
    """
    if isinstance(color, int):
        return _ansi_256(color, bg)

    if isinstance(color, str):
        color = color.strip()

        # Already an ANSI code
        if color.startswith("\x1b["):
            return color

        # Hex color
        if color.startswith("#"):
            color = color[1:]
            if len(color) == 3:
                color = "".join(c * 2 for c in color)
            if len(color) == 6:
                r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
                return _rgb_to_ansi(r, g, b, bg)

        # RGB function
        if color.startswith("rgb(") and color.endswith(")"):
            rgb_str = color[4:-1]
            r, g, b = map(int, rgb_str.split(","))
            return _rgb_to_ansi(r, g, b, bg)

    # Fallback to default
    return "\x1b[0m"


def _interpolate_color(
    color1: tuple[int, int, int], color2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    """Interpolate between two RGB colors."""
    r = int(color1[0] + (color2[0] - color1[0]) * t)
    g = int(color1[1] + (color2[1] - color1[1]) * t)
    b = int(color1[2] + (color2[2] - color1[2]) * t)
    return (r, g, b)


@dataclass(frozen=True, slots=True)
class ColorScheme:
    """Color scheme for the terminal UI."""

    # Text colors
    title: str = "#5E81AC"  # Nord blue
    artist: str = "#88C0D0"  # Nord frost
    current_line: str = "#A3BE8C"  # Nord green
    past_line: str = "#4C566A"  # Nord dark gray
    future_line: str = "#D8DEE9"  # Nord light gray
    dim_line: str = "#3B4252"  # Nord darker gray

    # UI elements
    border: str = "#434C5E"  # Nord gray
    progress_bar_filled: str = "#5E81AC"  # Nord blue
    progress_bar_empty: str = "#3B4252"  # Nord dark
    time_text: str = "#D8DEE9"  # Nord light
    status_playing: str = "#A3BE8C"  # Nord green
    status_paused: str = "#EBCB8B"  # Nord yellow
    warning: str = "#BF616A"  # Nord red

    # Background (optional, for future use)
    background: str = "#2E3440"  # Nord polar night

    # Special effects
    gradient_start: str = "#88C0D0"  # For gradient effects
    gradient_end: str = "#5E81AC"

    # Reset
    reset: str = "\x1b[0m"

    def to_ansi(self) -> ANSITheme:
        """Convert color scheme to ANSI escape codes."""
        return ANSITheme(
            title=_parse_color(self.title),
            artist=_parse_color(self.artist),
            current_line=_parse_color(self.current_line),
            past_line=_parse_color(self.past_line),
            future_line=_parse_color(self.future_line),
            dim_line=_parse_color(self.dim_line),
            border=_parse_color(self.border),
            progress_bar_filled=_parse_color(self.progress_bar_filled),
            progress_bar_empty=_parse_color(self.progress_bar_empty),
            time_text=_parse_color(self.time_text),
            status_playing=_parse_color(self.status_playing),
            status_paused=_parse_color(self.status_paused),
            warning=_parse_color(self.warning),
            background=_parse_color(self.background),
            gradient_start=_parse_color(self.gradient_start),
            gradient_end=_parse_color(self.gradient_end),
            reset=self.reset,
        )


@dataclass(frozen=True, slots=True)
class ANSITheme:
    """ANSI escape code theme for rendering."""

    title: str
    artist: str
    current_line: str
    past_line: str
    future_line: str
    dim_line: str
    border: str
    progress_bar_filled: str
    progress_bar_empty: str
    time_text: str
    status_playing: str
    status_paused: str
    warning: str
    background: str
    gradient_start: str
    gradient_end: str
    reset: str


# Predefined themes
THEMES: dict[str, ColorScheme] = {
    "default": ColorScheme(),
    "nord": ColorScheme(
        # Cold Nordic blues
        title="#5E81AC",
        artist="#88C0D0",
        current_line="#A3BE8C",
        past_line="#4C566A",
        future_line="#D8DEE9",
        dim_line="#3B4252",
        border="#434C5E",
        progress_bar_filled="#5E81AC",
        progress_bar_empty="#3B4252",
        time_text="#D8DEE9",
        status_playing="#A3BE8C",
        status_paused="#EBCB8B",
        warning="#BF616A",
        background="#2E3440",
        gradient_start="#88C0D0",
        gradient_end="#5E81AC",
    ),
    "dracula": ColorScheme(
        # Vampire purple + pink
        title="#FF79C6",
        artist="#BD93F9",
        current_line="#FF5555",
        past_line="#6272A4",
        future_line="#F8F8F2",
        dim_line="#44475A",
        border="#6272A4",
        progress_bar_filled="#FF79C6",
        progress_bar_empty="#44475A",
        time_text="#F8F8F2",
        status_playing="#50FA7B",
        status_paused="#F1FA8C",
        warning="#FF5555",
        background="#1E1F29",
        gradient_start="#FF79C6",
        gradient_end="#BD93F9",
    ),
    "monokai": ColorScheme(
        # Dark + lime green + coral pink
        title="#A6E22E",
        artist="#FD971F",
        current_line="#F92672",
        past_line="#75715E",
        future_line="#F8F8F2",
        dim_line="#49483E",
        border="#75715E",
        progress_bar_filled="#A6E22E",
        progress_bar_empty="#49483E",
        time_text="#F8F8F2",
        status_playing="#A6E22E",
        status_paused="#E6DB74",
        warning="#F92672",
        background="#1C1C1C",
        gradient_start="#A6E22E",
        gradient_end="#FD971F",
    ),
    "solarized_dark": ColorScheme(
        # Teal + amber on deep cyan-black
        title="#268BD2",
        artist="#2AA198",
        current_line="#B58900",
        past_line="#586E75",
        future_line="#93A1A1",
        dim_line="#073642",
        border="#586E75",
        progress_bar_filled="#268BD2",
        progress_bar_empty="#073642",
        time_text="#93A1A1",
        status_playing="#859900",
        status_paused="#B58900",
        warning="#DC322F",
        background="#073642",
        gradient_start="#2AA198",
        gradient_end="#B58900",
    ),
    "solarized_light": ColorScheme(
        # Inverted solarized — cream + burnt orange
        title="#268BD2",
        artist="#CB4B16",
        current_line="#859900",
        past_line="#93A1A1",
        future_line="#586E75",
        dim_line="#EEE8D5",
        border="#93A1A1",
        progress_bar_filled="#CB4B16",
        progress_bar_empty="#EEE8D5",
        time_text="#586E75",
        status_playing="#859900",
        status_paused="#B58900",
        warning="#DC322F",
        background="#FDF6E3",
        gradient_start="#CB4B16",
        gradient_end="#268BD2",
    ),
    "gruvbox": ColorScheme(
        # Warm retro greens + golds on charcoal
        title="#D79921",
        artist="#FABD2F",
        current_line="#B8BB26",
        past_line="#665C54",
        future_line="#EBDBB2",
        dim_line="#3C3836",
        border="#504945",
        progress_bar_filled="#B8BB26",
        progress_bar_empty="#3C3836",
        time_text="#EBDBB2",
        status_playing="#8EC07C",
        status_paused="#FABD2F",
        warning="#FB4934",
        background="#1D2021",
        gradient_start="#FABD2F",
        gradient_end="#B8BB26",
    ),
    "tokyo_night": ColorScheme(
        # Neon cyberpunk — blue + magenta + cyan
        title="#7AA2F7",
        artist="#BB9AF7",
        current_line="#73DACA",
        past_line="#565F89",
        future_line="#C0CAF5",
        dim_line="#1A1B26",
        border="#414868",
        progress_bar_filled="#7AA2F7",
        progress_bar_empty="#1A1B26",
        time_text="#C0CAF5",
        status_playing="#9ECE6A",
        status_paused="#E0AF68",
        warning="#F7768E",
        background="#1A1B26",
        gradient_start="#7AA2F7",
        gradient_end="#BB9AF7",
    ),
    "catppuccin": ColorScheme(
        # Pastel — soft blue + rose + green
        title="#89B4FA",
        artist="#F5C2E7",
        current_line="#A6E3A1",
        past_line="#6C7086",
        future_line="#CDD6F4",
        dim_line="#313244",
        border="#45475A",
        progress_bar_filled="#89B4FA",
        progress_bar_empty="#313244",
        time_text="#CDD6F4",
        status_playing="#A6E3A1",
        status_paused="#F9E2AF",
        warning="#F38BA8",
        background="#1E1E2E",
        gradient_start="#F5C2E7",
        gradient_end="#89B4FA",
    ),
    "synthwave": ColorScheme(
        # 80s retro — hot pink + electric blue + neon
        title="#FF00FF",
        artist="#00FFFF",
        current_line="#FF6EC7",
        past_line="#4A0072",
        future_line="#E0C0FF",
        dim_line="#2A1040",
        border="#4A0072",
        progress_bar_filled="#FF00FF",
        progress_bar_empty="#2A1040",
        time_text="#E0C0FF",
        status_playing="#00FFFF",
        status_paused="#FFE600",
        warning="#FF0040",
        background="#0A001A",
        gradient_start="#FF00FF",
        gradient_end="#00FFFF",
    ),
    "matrix": ColorScheme(
        # Green terminal — phosphor green on black
        title="#00FF41",
        artist="#00CC33",
        current_line="#00FF41",
        past_line="#006600",
        future_line="#00DD30",
        dim_line="#003300",
        border="#006600",
        progress_bar_filled="#00FF41",
        progress_bar_empty="#003300",
        time_text="#00DD30",
        status_playing="#00FF41",
        status_paused="#00AA22",
        warning="#FF0000",
        background="#000A00",
        gradient_start="#00FF41",
        gradient_end="#00AA22",
    ),
    "sunset": ColorScheme(
        # Warm orange → deep purple
        title="#FF6B35",
        artist="#F7931E",
        current_line="#FFD700",
        past_line="#4A1942",
        future_line="#FFB6C1",
        dim_line="#2D1B4E",
        border="#4A1942",
        progress_bar_filled="#FF6B35",
        progress_bar_empty="#2D1B4E",
        time_text="#FFB6C1",
        status_playing="#FFD700",
        status_paused="#FF8C00",
        warning="#DC143C",
        background="#1A0A2E",
        gradient_start="#FF6B35",
        gradient_end="#6B2FA0",
    ),
    "ocean": ColorScheme(
        # Deep sea — aquamarine + teal + coral
        title="#00CED1",
        artist="#20B2AA",
        current_line="#7FFFD4",
        past_line="#1A4A5E",
        future_line="#B0E0E6",
        dim_line="#0D2B3A",
        border="#1A4A5E",
        progress_bar_filled="#00CED1",
        progress_bar_empty="#0D2B3A",
        time_text="#B0E0E6",
        status_playing="#7FFFD4",
        status_paused="#FFB347",
        warning="#FF6347",
        background="#0A1628",
        gradient_start="#00CED1",
        gradient_end="#20B2AA",
    ),
    "cherry_blossom": ColorScheme(
        # Japanese sakura — soft pink + warm white
        title="#FFB7C5",
        artist="#FF69B4",
        current_line="#FFF0F5",
        past_line="#6B3A4A",
        future_line="#FFE4E1",
        dim_line="#3D1A2A",
        border="#6B3A4A",
        progress_bar_filled="#FFB7C5",
        progress_bar_empty="#3D1A2A",
        time_text="#FFE4E1",
        status_playing="#FFB7C5",
        status_paused="#FFDAB9",
        warning="#DC143C",
        background="#1F0F1A",
        gradient_start="#FFB7C5",
        gradient_end="#FF69B4",
    ),
    "cyberpunk": ColorScheme(
        # Neon yellow + hot magenta on dark
        title="#FFFF00",
        artist="#FF00AA",
        current_line="#00FF88",
        past_line="#3A1045",
        future_line="#FFE066",
        dim_line="#1A0A20",
        border="#3A1045",
        progress_bar_filled="#FFFF00",
        progress_bar_empty="#1A0A20",
        time_text="#FFE066",
        status_playing="#00FF88",
        status_paused="#FF00AA",
        warning="#FF0040",
        background="#0D0221",
        gradient_start="#FFFF00",
        gradient_end="#FF00AA",
    ),
    "forest": ColorScheme(
        # Earthy greens + brown
        title="#8FBC8F",
        artist="#66CDAA",
        current_line="#9ACD32",
        past_line="#3B5323",
        future_line="#C0D8C0",
        dim_line="#2A3C1A",
        border="#3B5323",
        progress_bar_filled="#8FBC8F",
        progress_bar_empty="#2A3C1A",
        time_text="#C0D8C0",
        status_playing="#9ACD32",
        status_paused="#DAA520",
        warning="#CD5C5C",
        background="#1A2F1A",
        gradient_start="#8FBC8F",
        gradient_end="#66CDAA",
    ),
    "lava": ColorScheme(
        # Magma — red orange yellow on near-black
        title="#FF4500",
        artist="#FF8C00",
        current_line="#FFD700",
        past_line="#3D0C02",
        future_line="#FFA07A",
        dim_line="#1A0500",
        border="#3D0C02",
        progress_bar_filled="#FF4500",
        progress_bar_empty="#1A0500",
        time_text="#FFA07A",
        status_playing="#FFD700",
        status_paused="#FF8C00",
        warning="#FF0000",
        background="#0A0000",
        gradient_start="#FF4500",
        gradient_end="#FFD700",
    ),
}


class ThemeManager:
    """Manages theme loading and customization."""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = config_dir or Path.home() / ".config" / "terminal_lyrics"
        self.themes_dir = self.config_dir / "themes"
        self.themes_dir.mkdir(parents=True, exist_ok=True)

    def get_theme(self, name: str = "default") -> ANSITheme:
        """Get a theme by name."""
        # Check built-in themes
        if name in THEMES:
            return THEMES[name].to_ansi()

        # Check custom themes
        theme_file = self.themes_dir / f"{name}.json"
        if theme_file.exists():
            return self.load_custom_theme(theme_file)

        # Fallback to default
        return THEMES["default"].to_ansi()

    def load_custom_theme(self, path: Path) -> ANSITheme:
        """Load a custom theme from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        scheme = ColorScheme(**data)
        return scheme.to_ansi()

    def save_theme(self, name: str, scheme: ColorScheme) -> None:
        """Save a custom theme to JSON file."""
        theme_file = self.themes_dir / f"{name}.json"

        data = {
            "title": scheme.title,
            "artist": scheme.artist,
            "current_line": scheme.current_line,
            "past_line": scheme.past_line,
            "future_line": scheme.future_line,
            "dim_line": scheme.dim_line,
            "border": scheme.border,
            "progress_bar_filled": scheme.progress_bar_filled,
            "progress_bar_empty": scheme.progress_bar_empty,
            "time_text": scheme.time_text,
            "status_playing": scheme.status_playing,
            "status_paused": scheme.status_paused,
            "warning": scheme.warning,
            "background": scheme.background,
            "gradient_start": scheme.gradient_start,
            "gradient_end": scheme.gradient_end,
        }

        with open(theme_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_themes(self) -> list[str]:
        """List all available themes."""
        themes = list(THEMES.keys())

        # Add custom themes
        if self.themes_dir.exists():
            for theme_file in self.themes_dir.glob("*.json"):
                themes.append(theme_file.stem)

        return sorted(set(themes))
