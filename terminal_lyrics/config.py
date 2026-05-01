from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal


def _config_dir() -> Path:
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "terminal_lyrics"
    return Path.home() / ".config" / "terminal_lyrics"


def _config_file() -> Path:
    return _config_dir() / "config.json"


@dataclass(frozen=True)
class VisualConfig:
    """Visual appearance configuration."""

    theme: str = "default"
    border_style: Literal["rounded", "double", "single", "heavy", "ascii"] = "rounded"
    show_progress_bar: bool = True
    show_metadata: bool = True
    show_visualizer: bool = False
    visualizer_style: Literal["equalizer", "waveform", "blocks", "dots", "centered"] = "equalizer"
    visualizer_motion: Literal["responsive", "smooth"] = "responsive"
    visualizer_position: Literal["top", "bottom", "off"] = "top"
    visualizer_bands: int = 20
    center_text: bool = True
    enable_animations: bool = True
    enable_gradient: bool = True
    enable_pulse: bool = True


@dataclass(frozen=True)
class AudioConfig:
    """Audio capture configuration."""

    audio_device: str | None = None  # None = auto-detect
    audio_backend: Literal["auto", "pulsectl", "sounddevice", "pyaudio"] = "auto"
    use_real_audio: bool = True


@dataclass(frozen=True)
class AppConfig:
    # Storage
    data_dir: Path
    cache_db_path: Path
    config_dir: Path

    # Locale
    lang: str

    # Sources
    sources: tuple[str, ...]
    api_min_interval_s: float
    api_max_retries: int
    api_backoff_base_s: float

    # MPRIS
    preferred_player: str | None

    # Rendering
    refresh_hz: float
    context_lines: int  # lines above/below current
    use_alt_screen: bool

    # Visual settings
    visual: VisualConfig

    # Audio settings
    audio: AudioConfig

    # Input
    enable_mouse: bool = True
    enable_media_controls: bool = True

    # Local ingest HTTP server (POST lyrics, prioritized on track change)
    ingest_enabled: bool = True
    ingest_host: str = "127.0.0.1"
    ingest_port: int = 7777
    ingest_wait_timeout_s: float = 5.0


def load_config() -> AppConfig:
    # XDG base dir fallback
    xdg = os.getenv("XDG_CACHE_HOME")
    data_dir = Path(xdg) if xdg else Path.home() / ".cache"
    data_dir = data_dir / "terminal_lyrics"

    sources_env = os.getenv("TERMINAL_LYRICS_SOURCES", "lrclib")
    sources = tuple(s.strip() for s in sources_env.split(",") if s.strip())

    refresh_hz = float(os.getenv("TERMINAL_LYRICS_REFRESH_HZ", "1000.0"))
    context_lines = int(os.getenv("TERMINAL_LYRICS_CONTEXT_LINES", "1"))
    use_alt_screen = os.getenv("TERMINAL_LYRICS_ALT_SCREEN", "1") not in ("0", "false", "False")
    enable_mouse = os.getenv("TERMINAL_LYRICS_MOUSE", "1") not in ("0", "false", "False")

    config_dir = _config_dir()
    lang = _load_lang(config_dir)
    visual = _load_visual_config(config_dir)
    audio = _load_audio_config(config_dir)
    input_cfg = _load_input_config(config_dir)
    enable_mouse = input_cfg["enable_mouse"]
    enable_media_controls = input_cfg["enable_media_controls"]

    ingest_enabled = os.getenv("TERMINAL_LYRICS_INGEST", "1") not in (
        "0",
        "",
        "false",
        "False",
    )
    ingest_host = os.getenv("TERMINAL_LYRICS_INGEST_HOST", "127.0.0.1").strip() or "127.0.0.1"
    ingest_port = int(os.getenv("TERMINAL_LYRICS_INGEST_PORT", "7777"))
    ingest_wait_timeout_s = float(os.getenv("TERMINAL_LYRICS_INGEST_WAIT_S", "5"))

    return AppConfig(
        data_dir=data_dir,
        cache_db_path=data_dir / "cache.sqlite3",
        config_dir=config_dir,
        lang=lang,
        sources=sources,
        api_min_interval_s=float(os.getenv("TERMINAL_LYRICS_API_MIN_INTERVAL", "5.0")),
        api_max_retries=int(os.getenv("TERMINAL_LYRICS_API_MAX_RETRIES", "3")),
        api_backoff_base_s=float(os.getenv("TERMINAL_LYRICS_API_BACKOFF_BASE", "1.0")),
        preferred_player=os.getenv("TERMINAL_LYRICS_PLAYER") or None,
        refresh_hz=refresh_hz,
        context_lines=context_lines,
        use_alt_screen=use_alt_screen,
        enable_mouse=enable_mouse,
        enable_media_controls=enable_media_controls,
        visual=visual,
        audio=audio,
        ingest_enabled=ingest_enabled,
        ingest_host=ingest_host,
        ingest_port=ingest_port,
        ingest_wait_timeout_s=ingest_wait_timeout_s,
    )


def _load_lang(config_dir: Path) -> str:
    # Priority: config.json → TERMINAL_LYRICS_LANG → "EN"
    cfg_path = config_dir / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw = (data.get("lang") or "en").upper()
            if raw in ("RU", "EN"):
                return raw
        except Exception:
            pass
    env_lang = os.getenv("TERMINAL_LYRICS_LANG")
    if env_lang and env_lang.upper() in ("RU", "EN"):
        return env_lang.upper()
    return "EN"


def _load_visual_config(config_dir: Path) -> VisualConfig:
    """Load visual configuration from config.json."""
    cfg_path = config_dir / "config.json"

    # Default values
    defaults = {
        "theme": "default",
        "border_style": "rounded",
        "show_progress_bar": True,
        "show_metadata": True,
        "show_visualizer": False,
        "visualizer_style": "equalizer",
        "visualizer_motion": "responsive",
        "visualizer_position": "top",
        "visualizer_bands": 20,
        "center_text": True,
        "enable_animations": True,
        "enable_gradient": True,
        "enable_pulse": True,
    }

    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            visual_data = data.get("visual", {})

            # Merge with defaults
            for key in defaults:
                if key in visual_data:
                    defaults[key] = visual_data[key]
        except Exception:
            pass

    # Environment variable overrides
    if theme := os.getenv("TERMINAL_LYRICS_THEME"):
        defaults["theme"] = theme
    if border := os.getenv("TERMINAL_LYRICS_BORDER_STYLE"):
        defaults["border_style"] = border
    if visualizer := os.getenv("TERMINAL_LYRICS_VISUALIZER"):
        defaults["show_visualizer"] = visualizer not in ("0", "false", "False")

    _valid_viz_styles = frozenset({"equalizer", "waveform", "blocks", "dots", "centered"})
    if defaults.get("visualizer_style") not in _valid_viz_styles:
        defaults["visualizer_style"] = "equalizer"

    _valid_viz_motion = frozenset({"responsive", "smooth"})
    if defaults.get("visualizer_motion") not in _valid_viz_motion:
        defaults["visualizer_motion"] = "responsive"

    if env_motion := os.getenv("TERMINAL_LYRICS_VISUALIZER_MOTION"):
        em = env_motion.strip().lower()
        if em in _valid_viz_motion:
            defaults["visualizer_motion"] = em

    # Validate visualizer_bands (must be between 3 and 50)
    if "visualizer_bands" in defaults:
        try:
            bands = int(defaults["visualizer_bands"])
            defaults["visualizer_bands"] = max(3, min(50, bands))
        except (ValueError, TypeError):
            defaults["visualizer_bands"] = 20

    return VisualConfig(**defaults)


def _load_audio_config(config_dir: Path) -> AudioConfig:
    """Load audio configuration from config.json."""
    cfg_path = config_dir / "config.json"

    # Default values
    defaults = {
        "audio_device": None,
        "audio_backend": "auto",
        "use_real_audio": True,
    }

    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            audio_data = data.get("audio", {})

            # Merge with defaults
            for key in defaults:
                if key in audio_data:
                    defaults[key] = audio_data[key]
        except Exception:
            pass

    # Environment variable overrides
    if device := os.getenv("TERMINAL_LYRICS_AUDIO_DEVICE"):
        defaults["audio_device"] = device
    if backend := os.getenv("TERMINAL_LYRICS_AUDIO_BACKEND"):
        defaults["audio_backend"] = backend
    if use_audio := os.getenv("TERMINAL_LYRICS_USE_REAL_AUDIO"):
        defaults["use_real_audio"] = use_audio not in ("0", "false", "False")

    return AudioConfig(**defaults)


def _load_input_config(config_dir: Path) -> dict:
    """Load input configuration from config.json."""
    cfg_path = config_dir / "config.json"
    defaults = {
        "enable_mouse": True,
        "enable_media_controls": True,
    }

    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            input_data = data.get("input", {})
            if "enable_mouse" in input_data:
                defaults["enable_mouse"] = bool(input_data["enable_mouse"])
            if "enable_media_controls" in input_data:
                defaults["enable_media_controls"] = bool(input_data["enable_media_controls"])
        except Exception:
            pass

    # Environment variable overrides config file
    env_mouse = os.getenv("TERMINAL_LYRICS_MOUSE")
    if env_mouse is not None:
        defaults["enable_mouse"] = env_mouse not in ("0", "false", "False")

    return defaults


def save_config_lang(lang: str) -> None:
    cfg_path = _config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["lang"] = lang.upper()
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_visual_config(visual: VisualConfig) -> None:
    """Save visual configuration to config.json."""
    cfg_path = _config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data["visual"] = {
        "theme": visual.theme,
        "border_style": visual.border_style,
        "show_progress_bar": visual.show_progress_bar,
        "show_metadata": visual.show_metadata,
        "show_visualizer": visual.show_visualizer,
        "visualizer_style": visual.visualizer_style,
        "visualizer_motion": visual.visualizer_motion,
        "visualizer_position": visual.visualizer_position,
        "visualizer_bands": visual.visualizer_bands,
        "center_text": visual.center_text,
        "enable_animations": visual.enable_animations,
        "enable_gradient": visual.enable_gradient,
        "enable_pulse": visual.enable_pulse,
    }

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_audio_config(audio: AudioConfig) -> None:
    """Save audio configuration to config.json."""
    cfg_path = _config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data["audio"] = {
        "audio_device": audio.audio_device,
        "audio_backend": audio.audio_backend,
        "use_real_audio": audio.use_real_audio,
    }

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_input_config(enable_mouse: bool, enable_media_controls: bool) -> None:
    """Save input configuration to config.json."""
    cfg_path = _config_file()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data["input"] = {
        "enable_mouse": enable_mouse,
        "enable_media_controls": enable_media_controls,
    }

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def list_audio_devices() -> list[dict[str, str | int]]:
    """List available audio input devices."""
    devices = []

    # Try pulsectl first
    try:
        import pulsectl

        pulse = pulsectl.Pulse("terminal_lyrics-list", connect=False)
        pulse.connect(autospawn=False)

        sources = pulse.source_list()
        for i, source in enumerate(sources):
            devices.append(
                {
                    "index": i,
                    "name": source.name,
                    "description": source.description,
                    "backend": "pulsectl",
                    "is_monitor": ".monitor" in source.name,
                }
            )
        pulse.close()
        return devices
    except Exception:
        pass

    # Try sounddevice
    try:
        import sounddevice as sd

        sd_devices = sd.query_devices()
        for i, dev in enumerate(sd_devices):
            if dev["max_input_channels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": dev["name"],
                        "description": dev["name"],
                        "backend": "sounddevice",
                        "is_monitor": any(
                            kw in dev["name"].lower() for kw in ["monitor", "loopback"]
                        ),
                    }
                )
        return devices
    except Exception:
        pass

    # Try pyaudio
    try:
        import pyaudio

        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append(
                    {
                        "index": i,
                        "name": info["name"],
                        "description": info["name"],
                        "backend": "pyaudio",
                        "is_monitor": any(
                            kw in info["name"].lower() for kw in ["monitor", "loopback"]
                        ),
                    }
                )
        p.terminate()
        return devices
    except Exception:
        pass

    return devices
