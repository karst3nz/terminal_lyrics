from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


BorderStyle = Literal["rounded", "double", "single", "heavy", "ascii"]


@dataclass(frozen=True, slots=True)
class BorderChars:
    """Characters for drawing borders."""

    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    horizontal: str
    vertical: str
    cross: str
    t_down: str
    t_up: str
    t_right: str
    t_left: str


BORDER_STYLES: dict[BorderStyle, BorderChars] = {
    "rounded": BorderChars(
        top_left="╭",
        top_right="╮",
        bottom_left="╰",
        bottom_right="╯",
        horizontal="─",
        vertical="│",
        cross="┼",
        t_down="┬",
        t_up="┴",
        t_right="├",
        t_left="┤",
    ),
    "double": BorderChars(
        top_left="╔",
        top_right="╗",
        bottom_left="╚",
        bottom_right="╝",
        horizontal="═",
        vertical="║",
        cross="╬",
        t_down="╦",
        t_up="╩",
        t_right="╠",
        t_left="╣",
    ),
    "single": BorderChars(
        top_left="┌",
        top_right="┐",
        bottom_left="└",
        bottom_right="┘",
        horizontal="─",
        vertical="│",
        cross="┼",
        t_down="┬",
        t_up="┴",
        t_right="├",
        t_left="┤",
    ),
    "heavy": BorderChars(
        top_left="┏",
        top_right="┓",
        bottom_left="┗",
        bottom_right="┛",
        horizontal="━",
        vertical="┃",
        cross="╋",
        t_down="┳",
        t_up="┻",
        t_right="┣",
        t_left="┫",
    ),
    "ascii": BorderChars(
        top_left="+",
        top_right="+",
        bottom_left="+",
        bottom_right="+",
        horizontal="-",
        vertical="|",
        cross="+",
        t_down="+",
        t_up="+",
        t_right="+",
        t_left="+",
    ),
}


def get_border_chars(style: BorderStyle = "rounded") -> BorderChars:
    """Get border characters for a given style."""
    return BORDER_STYLES.get(style, BORDER_STYLES["rounded"])


def draw_horizontal_line(width: int, border: BorderChars, left: str = "", right: str = "") -> str:
    """Draw a horizontal line with optional left/right characters."""
    if not left:
        left = border.horizontal
    if not right:
        right = border.horizontal

    inner_width = max(0, width - 2)
    return left + border.horizontal * inner_width + right


def draw_box_top(width: int, border: BorderChars) -> str:
    """Draw the top of a box."""
    return draw_horizontal_line(width, border, border.top_left, border.top_right)


def draw_box_bottom(width: int, border: BorderChars) -> str:
    """Draw the bottom of a box."""
    return draw_horizontal_line(width, border, border.bottom_left, border.bottom_right)


def draw_box_separator(width: int, border: BorderChars) -> str:
    """Draw a separator line inside a box."""
    return draw_horizontal_line(width, border, border.t_right, border.t_left)


def draw_box_line(
    text: str, width: int, border: BorderChars, align: Literal["left", "center", "right"] = "left"
) -> str:
    """Draw a line of text inside a box with borders."""
    inner_width = max(0, width - 2)

    # Strip ANSI codes for length calculation
    import re

    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    text_clean = ansi_escape.sub("", text)
    text_len = len(text_clean)

    if align == "center":
        padding_total = max(0, inner_width - text_len)
        padding_left = padding_total // 2
        padding_right = padding_total - padding_left
        content = " " * padding_left + text + " " * padding_right
    elif align == "right":
        padding = max(0, inner_width - text_len)
        content = " " * padding + text
    else:  # left
        padding = max(0, inner_width - text_len)
        content = text + " " * padding

    # Truncate if too long
    if len(ansi_escape.sub("", content)) > inner_width:
        # Simple truncation (doesn't handle ANSI perfectly, but good enough)
        content = content[:inner_width]

    return border.vertical + content + border.vertical


def truncate_text(text: str, max_width: int, suffix: str = "...") -> str:
    """Truncate text to fit within max_width, preserving ANSI codes."""
    import re

    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")

    # Extract ANSI codes and text
    parts = ansi_escape.split(text)
    codes = ansi_escape.findall(text)

    # Calculate visible length
    visible_text = "".join(parts)
    if len(visible_text) <= max_width:
        return text

    # Truncate and add suffix
    truncate_at = max(0, max_width - len(suffix))
    result = []
    current_len = 0

    for i, part in enumerate(parts):
        if current_len + len(part) <= truncate_at:
            if i > 0 and i - 1 < len(codes):
                result.append(codes[i - 1])
            result.append(part)
            current_len += len(part)
        else:
            remaining = truncate_at - current_len
            if remaining > 0:
                if i > 0 and i - 1 < len(codes):
                    result.append(codes[i - 1])
                result.append(part[:remaining])
            break

    return "".join(result) + suffix


def draw_progress_bar(
    current: float,
    total: float,
    width: int,
    filled_char: str = "━",
    empty_char: str = "─",
    show_percentage: bool = False,
) -> str:
    """
    Draw a progress bar.

    Args:
        current: Current progress value
        total: Total/max value
        width: Width of the progress bar
        filled_char: Character for filled portion
        empty_char: Character for empty portion
        show_percentage: Whether to show percentage in the middle

    Returns:
        Progress bar string
    """
    if total <= 0:
        ratio = 0.0
    else:
        ratio = max(0.0, min(1.0, current / total))

    if show_percentage:
        percentage_text = f" {int(ratio * 100)}% "
        text_len = len(percentage_text)
        bar_width = max(0, width - text_len)
    else:
        percentage_text = ""
        bar_width = width

    filled_width = int(bar_width * ratio)
    empty_width = bar_width - filled_width

    bar = filled_char * filled_width + empty_char * empty_width

    if show_percentage and bar_width > 0:
        # Insert percentage in the middle
        mid_point = bar_width // 2 - text_len // 2
        if mid_point >= 0:
            bar = bar[:mid_point] + percentage_text + bar[mid_point + text_len :]

    return bar


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    if seconds < 0:
        seconds = 0

    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def center_text(text: str, width: int) -> str:
    """Center text within a given width."""
    import re

    ansi_escape = re.compile(r"\x1b\[[0-9;]*m")
    text_clean = ansi_escape.sub("", text)
    text_len = len(text_clean)

    if text_len >= width:
        return text

    padding_total = width - text_len
    padding_left = padding_total // 2
    padding_right = padding_total - padding_left

    return " " * padding_left + text + " " * padding_right


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap text to fit within width, breaking at word boundaries.
    Preserves ANSI escape codes by applying the last seen codes to each new line.
    """
    import re

    ansi_escape = re.compile(r"(\x1b\[[0-9;]*m)")
    clean_width = len(ansi_escape.sub("", text))

    if clean_width <= width:
        return [text]

    lines = []
    words = text.split()
    current_line_words = []
    current_clean_len = 0
    last_codes = ""

    for word in words:
        word_clean = ansi_escape.sub("", word)
        word_len = len(word_clean)
        space_len = 1 if current_line_words else 0

        if current_clean_len + space_len + word_len <= width:
            current_line_words.append(word)
            current_clean_len += space_len + word_len
        else:
            if current_line_words:
                line = " ".join(current_line_words)
                if last_codes and not line.startswith("\x1b["):
                    line = last_codes + line
                lines.append(line)
            current_line_words = [word]
            current_clean_len = word_len

        # Track codes from current word for next line
        codes_in_word = ansi_escape.findall(word)
        if codes_in_word:
            last_codes = "".join(codes_in_word)

    if current_line_words:
        line = " ".join(current_line_words)
        if last_codes and not line.startswith("\x1b["):
            line = last_codes + line
        # Strip trailing reset codes — they'll be added by the renderer
        line = re.sub(r"(\x1b\[0m)+$", "", line)
        lines.append(line)

    return lines if lines else [text]


# Status icons
ICON_PLAYING = "▶"
ICON_PAUSED = "⏸"
ICON_STOPPED = "⏹"
ICON_MUSIC = "♫"
ICON_NOTE = "♪"
ICON_ALBUM = "💿"
ICON_ARTIST = "🎤"
ICON_CLOCK = "🕐"

# Alternative ASCII-safe icons
ICON_PLAYING_ASCII = ">"
ICON_PAUSED_ASCII = "||"
ICON_STOPPED_ASCII = "[]"
ICON_MUSIC_ASCII = "#"
