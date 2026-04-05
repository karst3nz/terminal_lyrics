from __future__ import annotations

import math
import time
from typing import Callable


def interpolate(start: float, end: float, t: float) -> float:
    """Linear interpolation between start and end."""
    return start + (end - start) * t


def ease_in_out(t: float) -> float:
    """Ease-in-out cubic easing function."""
    if t < 0.5:
        return 4 * t * t * t
    else:
        return 1 - pow(-2 * t + 2, 3) / 2


def ease_in(t: float) -> float:
    """Ease-in quadratic easing function."""
    return t * t


def ease_out(t: float) -> float:
    """Ease-out quadratic easing function."""
    return 1 - (1 - t) * (1 - t)


def pulse(t: float, frequency: float = 1.0) -> float:
    """Generate a pulsing value between 0 and 1."""
    return (math.sin(t * frequency * 2 * math.pi) + 1) / 2


def wave(t: float, frequency: float = 1.0, amplitude: float = 1.0) -> float:
    """Generate a wave value."""
    return math.sin(t * frequency * 2 * math.pi) * amplitude


class AnimationState:
    """Tracks animation state over time."""

    def __init__(self):
        self.start_time = time.time()
        self.last_update = self.start_time
        self.frame_count = 0

    def elapsed(self) -> float:
        """Get elapsed time since start."""
        return time.time() - self.start_time

    def delta(self) -> float:
        """Get time since last update."""
        now = time.time()
        dt = now - self.last_update
        self.last_update = now
        return dt

    def tick(self) -> int:
        """Increment frame count and return it."""
        self.frame_count += 1
        return self.frame_count

    def reset(self) -> None:
        """Reset animation state."""
        self.start_time = time.time()
        self.last_update = self.start_time
        self.frame_count = 0


def interpolate_rgb(
    color1: tuple[int, int, int], color2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    """Interpolate between two RGB colors."""
    r = int(color1[0] + (color2[0] - color1[0]) * t)
    g = int(color1[1] + (color2[1] - color1[1]) * t)
    b = int(color1[2] + (color2[2] - color1[2]) * t)
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def rgb_to_ansi(r: int, g: int, b: int, bg: bool = False) -> str:
    """Convert RGB to ANSI 24-bit color code."""
    code = 48 if bg else 38
    return f"\x1b[{code};2;{r};{g};{b}m"


def create_gradient(text: str, color1: str, color2: str, reset: str = "\x1b[0m") -> str:
    """Apply a gradient effect to text."""
    if not text:
        return text

    try:
        rgb1 = hex_to_rgb(color1)
        rgb2 = hex_to_rgb(color2)
    except (ValueError, IndexError):
        return text

    result = []
    text_len = len(text)

    for i, char in enumerate(text):
        if char == " ":
            result.append(char)
            continue

        t = i / max(1, text_len - 1)
        rgb = interpolate_rgb(rgb1, rgb2, t)
        result.append(rgb_to_ansi(*rgb) + char + reset)

    return "".join(result)


def fade_text(text: str, opacity: float, color: str, reset: str = "\x1b[0m") -> str:
    """Apply fade effect to text by adjusting color brightness."""
    if not text or opacity >= 1.0:
        return text

    try:
        rgb = hex_to_rgb(color)
    except (ValueError, IndexError):
        return text

    # Adjust brightness based on opacity
    faded_rgb = tuple(int(c * opacity) for c in rgb)
    color_code = rgb_to_ansi(*faded_rgb)

    return color_code + text + reset


def create_rainbow(text: str, offset: float = 0.0, reset: str = "\x1b[0m") -> str:
    """Apply rainbow effect to text."""
    if not text:
        return text

    result = []
    text_len = len(text)

    for i, char in enumerate(text):
        if char == " ":
            result.append(char)
            continue

        # Calculate hue based on position and offset
        hue = ((i / max(1, text_len - 1)) + offset) % 1.0
        rgb = hsv_to_rgb(hue, 1.0, 1.0)
        result.append(rgb_to_ansi(*rgb) + char + reset)

    return "".join(result)


def hsv_to_rgb(h: float, s: float, v: float) -> tuple[int, int, int]:
    """Convert HSV to RGB."""
    if s == 0.0:
        gray = int(v * 255)
        return (gray, gray, gray)

    h = h * 6.0
    i = int(h)
    f = h - i

    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    i = i % 6

    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q

    return (int(r * 255), int(g * 255), int(b * 255))


class PulseEffect:
    """Pulsing animation effect."""

    def __init__(self, frequency: float = 1.0, min_opacity: float = 0.3, max_opacity: float = 1.0):
        self.frequency = frequency
        self.min_opacity = min_opacity
        self.max_opacity = max_opacity
        self.start_time = time.time()

    def get_opacity(self) -> float:
        """Get current opacity value."""
        t = time.time() - self.start_time
        pulse_val = pulse(t, self.frequency)
        return self.min_opacity + (self.max_opacity - self.min_opacity) * pulse_val

    def apply(self, text: str, color: str, reset: str = "\x1b[0m") -> str:
        """Apply pulsing effect to text."""
        opacity = self.get_opacity()
        return fade_text(text, opacity, color, reset)


class WaveEffect:
    """Wave animation effect for multiple lines."""

    def __init__(self, frequency: float = 0.5, amplitude: float = 0.3):
        self.frequency = frequency
        self.amplitude = amplitude
        self.start_time = time.time()

    def get_offset(self, index: int) -> float:
        """Get wave offset for a given line index."""
        t = time.time() - self.start_time
        return wave(t + index * 0.2, self.frequency, self.amplitude)

    def get_opacity(self, index: int) -> float:
        """Get opacity for a given line index based on wave."""
        offset = self.get_offset(index)
        return 0.7 + offset * 0.3


class ScrollEffect:
    """Smooth scrolling effect."""

    def __init__(self, duration: float = 0.3):
        self.duration = duration
        self.start_time: float | None = None
        self.start_pos: int = 0
        self.target_pos: int = 0

    def start_scroll(self, from_pos: int, to_pos: int) -> None:
        """Start a scroll animation."""
        self.start_time = time.time()
        self.start_pos = from_pos
        self.target_pos = to_pos

    def get_position(self) -> float:
        """Get current scroll position."""
        if self.start_time is None:
            return float(self.target_pos)

        elapsed = time.time() - self.start_time
        if elapsed >= self.duration:
            self.start_time = None
            return float(self.target_pos)

        t = elapsed / self.duration
        t = ease_in_out(t)
        return interpolate(float(self.start_pos), float(self.target_pos), t)

    def is_animating(self) -> bool:
        """Check if animation is in progress."""
        return self.start_time is not None


class GradientEffect:
    """Animated gradient effect."""

    def __init__(self, colors: list[str], speed: float = 0.5):
        self.colors = colors
        self.speed = speed
        self.start_time = time.time()

    def get_colors(self) -> tuple[str, str]:
        """Get current gradient colors."""
        if len(self.colors) < 2:
            return (self.colors[0], self.colors[0]) if self.colors else ("#FFFFFF", "#FFFFFF")

        t = time.time() - self.start_time
        cycle = (t * self.speed) % len(self.colors)
        index = int(cycle)
        next_index = (index + 1) % len(self.colors)

        return (self.colors[index], self.colors[next_index])

    def apply(self, text: str, reset: str = "\x1b[0m") -> str:
        """Apply animated gradient to text."""
        color1, color2 = self.get_colors()
        return create_gradient(text, color1, color2, reset)


class SpinnerEffect:
    """Spinning animation effect."""

    SPINNERS = {
        "dots": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
        "line": ["-", "\\", "|", "/"],
        "arrow": ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
        "box": ["◰", "◳", "◲", "◱"],
        "circle": ["◐", "◓", "◑", "◒"],
        "music": ["♩", "♪", "♫", "♬"],
    }

    def __init__(self, style: str = "dots", speed: float = 10.0):
        self.frames = self.SPINNERS.get(style, self.SPINNERS["dots"])
        self.speed = speed
        self.start_time = time.time()

    def get_frame(self) -> str:
        """Get current spinner frame."""
        t = time.time() - self.start_time
        index = int(t * self.speed) % len(self.frames)
        return self.frames[index]
