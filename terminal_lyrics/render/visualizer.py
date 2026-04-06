from __future__ import annotations

import math
import random
import time
from typing import Literal, Optional
from venv import logger


VisualizerStyle = Literal["equalizer", "waveform"]


class MusicVisualizer:
    """20-band equalizer visualizer with waveform support."""

    def __init__(
        self,
        width: int = 20,
        height: int = 5,
        style: VisualizerStyle = "equalizer",
        use_real_audio: bool = True,
        audio_device: Optional[str] = None,
        audio_backend: str = "auto",
        waveform_style: Literal["simple", "detailed"] = "detailed",
    ):
        self.width = width
        self.height = height
        self.style = style
        self.waveform_style = waveform_style
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

            for i in range(min(self.width, len(frequency_data))):
                raw = frequency_data[i]  # уже [0..1]

                # Логарифмическое масштабирование — ближе к восприятию на слух
                # +epsilon чтобы не было log(0)
                boosted = math.log1p(raw * 40) / math.log1p(10)  # [0..1] → [0..1]

                target = int(boosted * self.height)

                current = self.bars[i]

                if target > current:
                    self.bars[i] = int(current * 0.2 + target * 0.8)  # быстрый подъём
                else:
                    self.bars[i] = int(current * 0.85 + target * 0.15)  # плавный спад

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
        if self.style == "waveform":
            return self._render_waveform()
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

    def _render_waveform(self) -> list[str]:
        """Render waveform-style visualization with symmetric bars.
        
        Creates a symmetric waveform visualization that expands outward
        from the center, similar to audio waveform displays.
        """
        lines = []
        center_row = self.height // 2
        
        for row in range(self.height - 1, -1, -1):
            line = ""
            dist_from_center = row - center_row
            
            for bar_height in self.bars:
                # Calculate distance from center (absolute value)
                abs_dist = abs(dist_from_center)
                
                if self.waveform_style == "simple":
                    # Simple style: small symmetric dots/bars expanding from center
                    if abs_dist == 0:
                        # Center row: show if any audio
                        if bar_height > 0:
                            line += "●"
                        else:
                            line += " "
                    elif abs_dist == 1:
                        # One row above/below center
                        if bar_height > 1:
                            line += "●"
                        else:
                            line += " "
                    else:
                        # Further rows: only for loud audio
                        if bar_height > 3:
                            line += " "
                        else:
                            line += " "
                else:
                    # Detailed style: smooth gradient from center
                    if abs_dist == 0:
                        # Center row
                        if bar_height >= 4:
                            line += "▓"
                        elif bar_height >= 2:
                            line += "▒"
                        elif bar_height >= 1:
                            line += "░"
                        else:
                            line += " "
                    elif abs_dist == 1:
                        # Adjacent rows
                        if bar_height >= 3:
                            line += "▒"
                        elif bar_height >= 2:
                            line += "░"
                        else:
                            line += " "
                    else:
                        # Outer rows
                        if bar_height >= 4:
                            line += "░"
                        else:
                            line += " "
            
            lines.append(line)

        return lines

    def _render_waveform_simple(self) -> list[str]:
        """Render a simpler waveform visualization matching the reference image style."""
        lines = []
        center_row = self.height // 2
        
        for row in range(self.height - 1, -1, -1):
            line = ""
            abs_dist = abs(row - center_row)
            
            for bar_height in self.bars:
                if abs_dist == 0:
                    # Center line - always show for active bars
                    if bar_height > 0:
                        line += "●"
                    else:
                        line += " "
                elif abs_dist == 1:
                    # One above/below - show for louder audio
                    if bar_height > 1:
                        line += "●"
                    else:
                        line += " "
                else:
                    # Further - only for very loud audio
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
