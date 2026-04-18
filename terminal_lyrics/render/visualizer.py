from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Literal, Optional


VisualizerStyle = Literal["equalizer", "waveform", "blocks", "dots", "centered"]
VisualizerMotion = Literal["responsive", "smooth"]


# ---------------------------------------------------------------------------
# Spectral bar display model (real audio)
#
# The analyzer passes f_i ∈ [0, 1], the fraction of total short-time spectral energy
# falling into band i. For a clean partition, sum_i f_i ≈ 1 (no per-frame max norm).
#
# Height mapping uses a concave g so weak bands are still visible without one band
# always pegging the scale:
#   g(f) = ln(1 + k·f) / ln(1 + k),  f ∈ [0,1],  g(0)=0, g(1)=1.
#
# Column height: h = min(H, g(f)·H·impact); transient term adds punch on sharp Δf without exceeding H.
# Temporal behavior is chosen per motion preset (responsive vs smooth).
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _VisualizerDynamics:
    spectral_map_k: float
    display_impact: float
    transient_punch: float
    smooth_attack: float
    smooth_release: float
    bass_release_boost: float
    silence_gate: float
    mid_band_blur_from: int
    blur_left: float
    blur_center: float
    blur_right: float
    decay_no_data: float
    decay_silence: float
    decay_paused: float


_MOTION_PRESETS: dict[VisualizerMotion, _VisualizerDynamics] = {
    "responsive": _VisualizerDynamics(
        spectral_map_k=52.0,
        display_impact=1.12,
        transient_punch=0.74,
        smooth_attack=0.88,
        smooth_release=0.48,
        bass_release_boost=1.22,
        silence_gate=3e-10,
        mid_band_blur_from=7,
        blur_left=0.12,
        blur_center=0.76,
        blur_right=0.12,
        decay_no_data=0.82,
        decay_silence=0.83,
        decay_paused=0.78,
    ),
    "smooth": _VisualizerDynamics(
        spectral_map_k=44.0,
        display_impact=0.98,
        transient_punch=0.35,
        smooth_attack=0.48,
        smooth_release=0.22,
        bass_release_boost=1.08,
        silence_gate=3e-10,
        mid_band_blur_from=5,
        blur_left=0.18,
        blur_center=0.64,
        blur_right=0.18,
        decay_no_data=0.90,
        decay_silence=0.91,
        decay_paused=0.88,
    ),
}


def _resolve_visualizer_motion(motion: str) -> VisualizerMotion:
    if motion == "smooth":
        return "smooth"
    return "responsive"


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
        motion: VisualizerMotion | str = "responsive",
    ):
        self.width = width
        self.height = height
        self.style = style
        self.waveform_style = waveform_style
        self._motion = _resolve_visualizer_motion(str(motion))
        self._dyn = _MOTION_PRESETS[self._motion]
        self.start_time = time.time()
        self.bars: list[int] = [0] * width
        self._smooth_levels: list[float] = [0.0] * width
        self._prev_raw_targets: list[float] = [0.0] * width
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
            dp = self._dyn.decay_paused
            for i in range(self.width):
                self._smooth_levels[i] *= dp
                self.bars[i] = max(0, int(round(self._smooth_levels[i])))
            return

        t = time.time() - self.start_time
        self.phase = t

        if self.audio_analyzer and self.audio_analyzer.is_running():
            self._update_from_audio()
        else:
            self._update_simulation(t)

    def _spectral_fraction_to_height(self, frac: float) -> float:
        """Map energy fraction f ∈ [0,1] to target bar height in rows (concave in f)."""
        k = self._dyn.spectral_map_k
        impact = self._dyn.display_impact
        height = self.height
        f = max(0.0, min(1.0, frac))
        g = math.log1p(k * f) / math.log1p(k)
        return min(float(height), g * float(height) * impact)

    def _blur_upper_bands(self, values: list[float], from_index: int) -> list[float]:
        """3-tap blur on indices >= from_index; lower indices unchanged (no bass bleed)."""
        n = len(values)
        if n <= 2 or from_index >= n:
            return list(values)
        wL, wC, wR = self._dyn.blur_left, self._dyn.blur_center, self._dyn.blur_right
        out = list(values)
        for i in range(from_index, n):
            left = values[i - 1]
            center = values[i]
            right = values[i + 1] if i < n - 1 else values[i]
            out[i] = wL * left + wC * center + wR * right
        return out

    def _apply_transient_punch(self, raw_targets: list[float]) -> list[float]:
        """Boost columns when the spectral target jumps up sharply (beats, snares)."""
        out: list[float] = []
        cap = float(self.height)
        for i in range(self.width):
            prev = self._prev_raw_targets[i]
            raw = raw_targets[i]
            rise = max(0.0, raw - prev)
            self._prev_raw_targets[i] = raw
            punched = min(cap, raw + rise * self._dyn.transient_punch)
            out.append(punched)
        return out

    def _apply_level_smoothing(self, targets: list[float]) -> None:
        """EMA toward per-column target heights; bass rows decay slightly faster on the way down."""
        d = self._dyn
        hmax = self.height
        for i in range(self.width):
            tgt = targets[i]
            cur = self._smooth_levels[i]
            k = d.smooth_attack if tgt > cur else d.smooth_release
            if i < 4 and tgt < cur:
                k = min(1.0, d.smooth_release * d.bass_release_boost)
            cur = cur + (tgt - cur) * k
            self._smooth_levels[i] = cur
            self.bars[i] = max(0, min(int(round(cur)), hmax))

    def _decay_smoothed(self, factor: float) -> None:
        hmax = self.height
        for i in range(self.width):
            self._smooth_levels[i] *= factor
            self.bars[i] = max(0, min(int(round(self._smooth_levels[i])), hmax))

    def _update_from_audio(self) -> None:
        """fraction of spectrum per band → target heights → temporal smoothing."""
        try:
            frequency_data = self.audio_analyzer.get_frequency_data()

            if not frequency_data:
                self._decay_smoothed(self._dyn.decay_no_data)
                return

            n_in = len(frequency_data)
            frac = [max(0.0, float(frequency_data[i])) for i in range(min(n_in, self.width))]
            if len(frac) < self.width:
                frac.extend([0.0] * (self.width - len(frac)))

            peak = max(frac) if frac else 0.0
            if peak < self._dyn.silence_gate:
                self._decay_smoothed(self._dyn.decay_silence)
                return

            frac = self._blur_upper_bands(frac, self._dyn.mid_band_blur_from)
            s = sum(frac)
            if s > 0:
                frac = [x / s for x in frac]

            raw_targets = [self._spectral_fraction_to_height(f) for f in frac]
            targets = self._apply_transient_punch(raw_targets)

            self._apply_level_smoothing(targets)

        except Exception:
            self._update_simulation(time.time() - self.start_time)

    def _update_simulation(self, t: float) -> None:
        """Synthetic energy per band, renormalized to fractions (same mapping as real audio)."""
        energy: list[float] = []
        for i in range(self.width):
            bass_freq = 0.9 + math.sin(t * 0.35) * 3.2
            mid_freq = 2.2 + math.sin(t * 0.55) * 4.5
            treble_freq = 4.5 + math.sin(t * 0.85) * 8.0

            pos_ratio = i / max(1, self.width - 1)

            bass = (math.sin(t * bass_freq * 2 * math.pi + i * 0.12) + 1) / 2
            bass *= 1.0 - pos_ratio * 0.65

            mid = (math.sin(t * mid_freq * 2 * math.pi + i * 0.35) + 1) / 2
            mid *= 1.0 - abs(pos_ratio - 0.5) * 0.48

            treble = (math.sin(t * treble_freq * 2 * math.pi + i * 0.55) + 1) / 2
            treble *= pos_ratio * 0.85

            shimmer = 0.18 * math.sin(t * 11.0 + i * 0.9)
            combined = (bass * 0.38 + mid * 0.36 + treble * 0.26) * 1.02 + shimmer
            combined += random.random() * 0.16

            if random.random() > 0.82:
                combined = min(1.2, combined + random.random() * 0.55)

            energy.append(max(0.0, combined))

        s = sum(energy)
        if s <= 1e-12:
            fracs = [1.0 / self.width] * self.width
        else:
            fracs = [e / s for e in energy]

        fracs = self._blur_upper_bands(fracs, self._dyn.mid_band_blur_from)
        s2 = sum(fracs)
        if s2 > 0:
            fracs = [x / s2 for x in fracs]

        raw_targets = [self._spectral_fraction_to_height(f) for f in fracs]
        targets = self._apply_transient_punch(raw_targets)
        self._apply_level_smoothing(targets)

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
        if self.style == "blocks":
            return self._render_blocks()
        if self.style == "dots":
            return self._render_dots()
        if self.style == "centered":
            return self._render_centered()
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

    def _render_blocks(self) -> list[str]:
        """Bars grow bottom-up; full rows use █, the top row uses ▁▂▃▄▅▆▇ for the fraction."""
        shades = "▁▂▃▄▅▆▇█"
        n = len(shades)
        lines: list[str] = []
        cap = max(float(self.height), 1.0)

        for row in range(self.height - 1, -1, -1):
            line = ""
            for bar_height in self.bars:
                bh = float(min(max(bar_height, 0), cap * 2))
                if bh <= row:
                    line += " "
                elif bh >= row + 1:
                    line += "█"
                else:
                    rem = bh - row
                    idx = min(int(rem * n), n - 1)
                    line += shades[idx]
            lines.append(line)
        return lines

    def _render_dots(self) -> list[str]:
        """Render pointillist style with dot accents."""
        lines: list[str] = []
        for row in range(self.height - 1, -1, -1):
            line = ""
            for bar_height in self.bars:
                if bar_height <= row:
                    line += " "
                    continue
                depth = bar_height - row
                if depth >= 3:
                    line += "●"
                elif depth == 2:
                    line += "◉"
                else:
                    line += "•"
            lines.append(line)
        return lines

    def _render_centered(self) -> list[str]:
        """Render bars mirrored around center line."""
        lines: list[str] = []
        center_row = self.height // 2
        for row in range(self.height - 1, -1, -1):
            line = ""
            dist = abs(row - center_row)
            for bar_height in self.bars:
                amp = max(0, int(bar_height / 2))
                if amp > dist:
                    line += "█" if dist == 0 else "▓"
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
        # Keep title icon readable across terminals/fonts.
        # Some fonts render low bars (e.g. ▁) almost like "_" in headers.
        notes = ["♫", "♬", "♪", "♩"]
        idx = int(self.phase * len(notes)) % len(notes)
        return notes[idx]

    def get_frame(self) -> str:
        return self.render()
