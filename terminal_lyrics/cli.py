from __future__ import annotations

from pathlib import Path
import typer

from terminal_lyrics.app import watch as watch_loop
from terminal_lyrics.cache.sqlite import LyricsCache
from terminal_lyrics.config import (
    load_config,
    save_config_lang,
    save_visual_config,
    save_audio_config,
    VisualConfig,
    AudioConfig,
    list_audio_devices,
)
from terminal_lyrics.i18n import set_lang, t
from terminal_lyrics.logging_setup import setup_logging
from terminal_lyrics.lrc.export import export_json, export_lrc, export_srt
from terminal_lyrics.lrc.parse import parse_lrc_with_stats
from terminal_lyrics.mpris.client import MprisClient
from terminal_lyrics.sources.service import LyricsService
from terminal_lyrics.render.themes import ThemeManager


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def watch(
    player: str | None = typer.Option(
        None, "--player", help="MPRIS service or short name (e.g. vlc)"
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    log_file: bool = typer.Option(
        False,
        "--log-file",
        help="Write logs to file (~/.cache/terminal-lyrics/terminal-lyrics.log)",
    ),
    refresh_hz: float | None = typer.Option(None, "--refresh-hz", help="Polling frequency (Hz)"),
    no_alt_screen: bool = typer.Option(
        False, "--no-alt-screen", help="Do not use alternate screen buffer"
    ),
    context_lines: int | None = typer.Option(
        None, "--context", help="Lines above/below current line"
    ),
):
    """Watch synced lyrics in terminal (tmux/headless friendly)."""
    cfg = load_config()
    set_lang(cfg.lang)
    if refresh_hz is not None:
        cfg = cfg.__class__(**{**cfg.__dict__, "refresh_hz": refresh_hz})
    if context_lines is not None:
        cfg = cfg.__class__(**{**cfg.__dict__, "context_lines": context_lines})
    if no_alt_screen:
        cfg = cfg.__class__(**{**cfg.__dict__, "use_alt_screen": False})

    setup_logging(debug, log_to_file=log_file)
    raise typer.Exit(
        code=watch_loop(cfg, preferred_player=player or cfg.preferred_player, debug=debug)
    )


@app.command()
def players():
    """List available MPRIS players."""
    for p in MprisClient.list_players():
        typer.echo(p)


@app.command()
def parse(lrc_path: Path):
    """Parse LRC and print stats."""
    text = lrc_path.read_text(encoding="utf-8")
    doc, stats = parse_lrc_with_stats(text)
    typer.echo(f"lines_total={stats.lines_total}")
    typer.echo(f"lines_with_timestamps={stats.lines_with_timestamps}")
    typer.echo(f"lines_ignored={stats.lines_ignored}")
    typer.echo(f"events_total={stats.events_total}")
    typer.echo(f"offset_ms={doc.offset_ms}")
    typer.echo(f"tags={doc.tags or {}}")


@app.command()
def export(
    lrc_path: Path,
    fmt: str = typer.Option("srt", "--format", case_sensitive=False, help="lrc|srt|json"),
    out: Path | None = typer.Option(None, "--out", help="Output file (default: stdout)"),
):
    """Export LRC to SRT/JSON/LRC (normalized)."""
    cfg = load_config()
    set_lang(cfg.lang)
    text = lrc_path.read_text(encoding="utf-8")
    doc, _stats = parse_lrc_with_stats(text)
    fmt_l = fmt.lower()
    if fmt_l == "json":
        data = export_json(doc)
    elif fmt_l == "lrc":
        data = export_lrc(doc)
    elif fmt_l == "srt":
        data = export_srt(doc)
    else:
        raise typer.BadParameter(t("format_must_be"))

    if out:
        out.write_text(data, encoding="utf-8")
    else:
        typer.echo(data, nl=False)


@app.command()
def cache(
    clear: bool = typer.Option(False, "--clear", help="Clear lyrics cache"),
):
    """Manage lyrics cache."""
    cfg = load_config()
    set_lang(cfg.lang)
    cache_db = LyricsCache(cfg.cache_db_path)
    if clear:
        cache_db.clear()
        typer.echo(t("cache_cleared", path=str(cfg.cache_db_path)))
    else:
        typer.echo(t("use_clear_to_clear"))


@app.command()
def search(
    q: str | None = typer.Option(None, "--query", "-q", help="Search keyword in any field"),
    track: str | None = typer.Option(None, "--track", "-t", help="Search in track name"),
    artist: str | None = typer.Option(None, "--artist", "-a", help="Search in artist name"),
    album: str | None = typer.Option(None, "--album", help="Search in album name"),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum results to show"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """
    Search for lyrics in lrclib database.

    At least one of --query or --track must be provided.
    """
    cfg = load_config()
    set_lang(cfg.lang)
    if not q and not track:
        typer.echo(t("search_query_required"), err=True)
        raise typer.Exit(code=1)

    service = LyricsService(cfg)
    results = service.search(q=q, track_name=track, artist_name=artist, album_name=album)

    if not results:
        typer.echo(t("no_results_found"))
        return

    # Ограничиваем количество результатов
    results = results[:limit]

    if json_output:
        import json

        typer.echo(
            json.dumps(
                [
                    {
                        "id": r.id,
                        "track_name": r.track_name,
                        "artist_name": r.artist_name,
                        "album_name": r.album_name,
                        "duration": r.duration,
                        "instrumental": r.instrumental,
                        "has_synced_lyrics": r.has_synced_lyrics,
                        "has_plain_lyrics": r.has_plain_lyrics,
                    }
                    for r in results
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for i, r in enumerate(results, 1):
            synced = "✓" if r.has_synced_lyrics else "✗"
            plain = "✓" if r.has_plain_lyrics else "✗"
            duration_str = f"{r.duration // 60}:{r.duration % 60}" if r.duration else "?"
            inst_str = t("instrumental") if r.instrumental else ""
            typer.echo(f"{i}. {r.artist_name} - {r.track_name} ({duration_str}){inst_str}")
            if r.album_name:
                typer.echo(f"   {t('album')}: {r.album_name}")
            typer.echo(f"   {t('synced')}: {synced}  {t('plain')}: {plain}")
            if r.id:
                typer.echo(f"   ID: {r.id}")
            typer.echo()


@app.command()
def config(
    lang: str | None = typer.Option(None, "--lang", help="Set language: RU or EN"),
    theme: str | None = typer.Option(None, "--theme", help="Set color theme"),
    list_themes: bool = typer.Option(False, "--list-themes", help="List available themes"),
    border: str | None = typer.Option(
        None, "--border", help="Set border style: rounded, double, single, heavy, ascii"
    ),
    progress_bar: bool | None = typer.Option(
        None, "--progress-bar/--no-progress-bar", help="Show/hide progress bar"
    ),
    visualizer: bool | None = typer.Option(
        None, "--visualizer/--no-visualizer", help="Enable/disable music visualizer"
    ),
    visualizer_style: str | None = typer.Option(
        None,
        "--visualizer-style",
        help="Visualizer style: bars, wave, pulse, spectrum, notes, equalizer",
    ),
    center_text: bool | None = typer.Option(
        None, "--center-text/--no-center-text", help="Center lyrics text"
    ),
    animations: bool | None = typer.Option(
        None, "--animations/--no-animations", help="Enable/disable animations"
    ),
):
    """Manage settings (language, theme, visual options, etc.)."""
    cfg = load_config()
    set_lang(cfg.lang)

    # List themes
    if list_themes:
        theme_manager = ThemeManager(cfg.config_dir)
        themes = theme_manager.list_themes()
        typer.echo("Available themes:")
        for t_name in themes:
            marker = " (current)" if t_name == cfg.visual.theme else ""
            typer.echo(f"  - {t_name}{marker}")
        return

    # Update language
    if lang is not None:
        lang_upper = lang.upper()
        if lang_upper not in ("RU", "EN"):
            typer.echo(t("lang_invalid"), err=True)
            raise typer.Exit(code=1)
        save_config_lang(lang_upper)
        set_lang(lang_upper)
        typer.echo(t("lang_set", lang=lang_upper))

    # Update visual settings
    visual_changed = False
    visual_dict = {
        "theme": cfg.visual.theme,
        "border_style": cfg.visual.border_style,
        "show_progress_bar": cfg.visual.show_progress_bar,
        "show_metadata": cfg.visual.show_metadata,
        "show_visualizer": cfg.visual.show_visualizer,
        "visualizer_style": cfg.visual.visualizer_style,
        "visualizer_position": cfg.visual.visualizer_position,
        "center_text": cfg.visual.center_text,
        "enable_animations": cfg.visual.enable_animations,
        "enable_gradient": cfg.visual.enable_gradient,
        "enable_pulse": cfg.visual.enable_pulse,
    }

    if theme is not None:
        visual_dict["theme"] = theme
        visual_changed = True
        typer.echo(f"Theme set to: {theme}")

    if border is not None:
        if border not in ("rounded", "double", "single", "heavy", "ascii"):
            typer.echo(
                "Invalid border style. Choose: rounded, double, single, heavy, ascii", err=True
            )
            raise typer.Exit(code=1)
        visual_dict["border_style"] = border
        visual_changed = True
        typer.echo(f"Border style set to: {border}")

    if progress_bar is not None:
        visual_dict["show_progress_bar"] = progress_bar
        visual_changed = True
        typer.echo(f"Progress bar: {'enabled' if progress_bar else 'disabled'}")

    if visualizer is not None:
        visual_dict["show_visualizer"] = visualizer
        visual_changed = True
        typer.echo(f"Visualizer: {'enabled' if visualizer else 'disabled'}")

    if visualizer_style is not None:
        if visualizer_style not in ("equalizer", "waveform"):
            typer.echo("Invalid visualizer style. Choose: equalizer, waveform", err=True)
            raise typer.Exit(code=1)
        visual_dict["visualizer_style"] = visualizer_style
        visual_changed = True
        typer.echo(f"Visualizer style: {visualizer_style}")

    if center_text is not None:
        visual_dict["center_text"] = center_text
        visual_changed = True
        typer.echo(f"Center text: {'enabled' if center_text else 'disabled'}")

    if animations is not None:
        visual_dict["enable_animations"] = animations
        visual_changed = True
        typer.echo(f"Animations: {'enabled' if animations else 'disabled'}")

    if visual_changed:
        new_visual = VisualConfig(**visual_dict)
        save_visual_config(new_visual)
        typer.echo("Visual settings saved!")

    # Show current settings if no options provided
    if not any(
        [
            lang,
            theme,
            list_themes,
            border,
            progress_bar,
            visualizer,
            visualizer_style,
            center_text,
            animations,
        ]
    ):
        typer.echo(t("lang_current", lang=cfg.lang))
        typer.echo(f"Theme: {cfg.visual.theme}")
        typer.echo(f"Border style: {cfg.visual.border_style}")
        typer.echo(f"Progress bar: {'enabled' if cfg.visual.show_progress_bar else 'disabled'}")
        typer.echo(f"Visualizer: {'enabled' if cfg.visual.show_visualizer else 'disabled'}")
        typer.echo(f"Visualizer style: {cfg.visual.visualizer_style}")
        typer.echo(f"Center text: {'enabled' if cfg.visual.center_text else 'disabled'}")
        typer.echo(f"Animations: {'enabled' if cfg.visual.enable_animations else 'disabled'}")


@app.command()
def configure():
    """Interactive visual configuration (TUI)."""
    from terminal_lyrics.tui_config import run

    run()


@app.command()
def audio(
    list_devices: bool = typer.Option(False, "--list-devices", help="List available audio devices"),
    set_device: str | None = typer.Option(None, "--set-device", help="Set audio device by name"),
    backend: str | None = typer.Option(
        None, "--backend", help="Set audio backend: auto, pulsectl, sounddevice, pyaudio"
    ),
    enable: bool | None = typer.Option(
        None, "--enable/--disable", help="Enable/disable real audio capture"
    ),
):
    """Manage audio capture settings."""
    cfg = load_config()
    set_lang(cfg.lang)

    # List devices
    if list_devices:
        devices = list_audio_devices()
        if not devices:
            typer.echo("No audio devices found. Make sure audio libraries are installed.")
            typer.echo("Install: pip install pulsectl sounddevice")
            return

        typer.echo("Available audio input devices:\n")
        for dev in devices:
            monitor_marker = " [MONITOR]" if dev.get("is_monitor") else ""
            current_marker = " (current)" if dev["name"] == cfg.audio.audio_device else ""
            typer.echo(f"  [{dev['index']}] {dev['description']}{monitor_marker}{current_marker}")
            typer.echo(f"      Backend: {dev['backend']}")
            typer.echo(f"      Name: {dev['name']}")
            typer.echo()

        typer.echo("\nTip: Use --set-device with the device name to configure it")
        return

    # Update audio settings
    audio_changed = False
    audio_dict = {
        "audio_device": cfg.audio.audio_device,
        "audio_backend": cfg.audio.audio_backend,
        "use_real_audio": cfg.audio.use_real_audio,
    }

    if set_device is not None:
        audio_dict["audio_device"] = set_device
        audio_changed = True
        typer.echo(f"Audio device set to: {set_device}")

    if backend is not None:
        if backend not in ("auto", "pulsectl", "sounddevice", "pyaudio"):
            typer.echo("Invalid backend. Choose: auto, pulsectl, sounddevice, pyaudio", err=True)
            raise typer.Exit(code=1)
        audio_dict["audio_backend"] = backend
        audio_changed = True
        typer.echo(f"Audio backend set to: {backend}")

    if enable is not None:
        audio_dict["use_real_audio"] = enable
        audio_changed = True
        typer.echo(f"Real audio capture: {'enabled' if enable else 'disabled'}")

    if audio_changed:
        new_audio = AudioConfig(**audio_dict)
        save_audio_config(new_audio)
        typer.echo("Audio settings saved!")

    # Show current settings if no options provided
    if not any([list_devices, set_device, backend, enable is not None]):
        typer.echo(f"Audio device: {cfg.audio.audio_device or 'auto-detect'}")
        typer.echo(f"Audio backend: {cfg.audio.audio_backend}")
        typer.echo(f"Real audio capture: {'enabled' if cfg.audio.use_real_audio else 'disabled'}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
