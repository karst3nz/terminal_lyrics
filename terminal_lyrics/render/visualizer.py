from __future__ import annotations

import math
import random
import time
from typing import Literal, Optional


VisualizerStyle = Literal["equalizer"]


class MusicVisualizer:
    """20-band equalizer visualizer."""

    def __init__(
        self,
        width: int = 20,
        height: int = 5,
        style: VisualizerStyle = "equalizer",
        use_real_audio: bool = True,
        audio_device: Optional[str] = None,
        audio_backend: str = "auto",
    ):
        self.width = width
        self.height = height
        self.style = style
        self.start_time = time.time()
        self.bars: list[int] = [0] * width
        self.phase = 0.0
        self.use_real_audio = use_real_audio
        self.audio_analyzer = None

        if use_real_audio:
            try:
                from terminal_lyrics.audio import get_audio_analyzer

                self.audio_analyzer = get_audio_analyzer(
                    num_bands=width, device_name=audio_device, preferred_backend=audio_backend
                )
                if self.audio_analyzer.is_available():
                    self.audio_analyzer.start()
                else:
                    self.audio_analyzer = None
            except Exception:
                self.audio_analyzer = None

    def update(self, is_playing: bool = True) -> None:
        """Update visualizer state."""
        if not is_playing:
            self.bars = [max(0, int(b * 0.85)) for b in self.bars]
            return

        t = time.time() - self.start_time
        self.phase = t

        if self.audio_analyzer and self.audio_analyzer.is_running():
            self._update_from_audio()
        else:
            self._update_simulation(t)

    def _update_from_audio(self):
        """Update bars from real audio data."""
        try:
            frequency_data = self.audio_analyzer.get_frequency_data()

            if not frequency_data or all(v == 0.0 for v in frequency_data):
                return

            max_val = max(frequency_data)
            if max_val == 0:
                return

            for i in range(min(self.width, len(frequency_data))):
                scaled = frequency_data[i] / max_val
                boosted = scaled ** 0.6
                target = int(boosted * (self.height + 1))

                current = self.bars[i]
                diff = target - current

                if diff > 0:
                    self.bars[i] = int(current * 0.1 + target * 0.9)
                else:
                    self.bars[i] = int(current * 0.8 + target * 0.2)
        except Exception:
            self._update_simulation(time.time() - self.start_time)

    def _update_simulation(self, t: float):
        """Update bars with simulated audio data."""
        for i in range(self.width):
            bass_freq = 0.8 + math.sin(t * 0.3) * 0.2
            mid_freq = 2.0 + math.sin(t * 0.5) * 0.5
            treble_freq = 4.0 + math.sin(t * 0.7) * 1.0

            pos_ratio = i / max(1, self.width - 1)

            bass = (math.sin(t * bass_freq * 2 * math.pi + i * 0.1) + 1) / 2
            bass *= 1.0 - pos_ratio * 0.7

            mid = (math.sin(t * mid_freq * 2 * math.pi + i * 0.3) + 1) / 2
            mid *= 1.0 - abs(pos_ratio - 0.5) * 0.5

            treble = (math.sin(t * treble_freq * 2 * math.pi + i * 0.5) + 1) / 2
            treble *= pos_ratio * 0.8

            combined = (bass * 0.4 + mid * 0.35 + treble * 0.25) * 0.9
            combined += random.random() * 0.1

            if random.random() > 0.95:
                combined = min(1.0, combined + random.random() * 0.3)

            target = int(combined * (self.height + 2))
            current = self.bars[i]
            self.bars[i] = int(current * 0.6 + target * 0.4)

    def cleanup(self) -> None:
        """Cleanup resources, stop audio analyzer if running."""
        if self.audio_analyzer:
            try:
                if hasattr(self.audio_analyzer, "stop"):
                    self.audio_analyzer.stop()
            except Exception:
                pass

    def render(self) -> list[str]:
        """Render visualizer as list of lines."""
        return self._render_equalizer()

    def _render_equalizer(self) -> list[str]:
        """Render as 20-band equalizer with gradient shading."""
        lines = []

        for row in range(self.height - 1, -1, -1):
            line = ""
            for bar_height in self.bars:
                if bar_height > row:
                    if bar_height - row > 2:
                        line += "█"
                    elif bar_height - row > 1:
                        line += "▓"
                    else:
                        line += "▒"
                else:
                    line += " "
            lines.append(line)

        return lines


class SimpleVisualizer:
    """Simple animated equalizer icon for compact display."""

    def __init__(self, style: str = "equalizer", speed: float = 5.0):
        self.style = style
        self.speed = speed
        self.start_time = time.time()
        self.phase = 0.0

    def update(self, is_playing: bool = True) -> None:
        if is_playing:
            elapsed = time.time() - self.start_time
            self.phase = (elapsed * self.speed) % 1.0

    def render(self) -> str:
        bars = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
        idx = int(self.phase * len(bars))
        return bars[idx]

    def get_frame(self) -> str:
        return self.render()
