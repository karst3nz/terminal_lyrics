from __future__ import annotations

from pathlib import Path
import typer

from terminal_lyrics.app import watch as watch_loop
from terminal_lyrics.cache.sqlite import LyricsCache
from terminal_lyrics.config import load_config
from terminal_lyrics.logging_setup import setup_logging
from terminal_lyrics.lrc.export import export_json, export_lrc, export_srt
from terminal_lyrics.lrc.parse import parse_lrc_with_stats
from terminal_lyrics.mpris.client import MprisClient
from terminal_lyrics.sources.service import LyricsService


app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def watch(
    player: str | None = typer.Option(None, "--player", help="MPRIS service or short name (e.g. vlc)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
    refresh_hz: float | None = typer.Option(None, "--refresh-hz", help="Polling frequency (Hz)"),
    no_alt_screen: bool = typer.Option(False, "--no-alt-screen", help="Do not use alternate screen buffer"),
    context_lines: int | None = typer.Option(None, "--context", help="Lines above/below current line"),
):
    """
    Watch synced lyrics in terminal (tmux/headless friendly).
    """
    cfg = load_config()
    if refresh_hz is not None:
        cfg = cfg.__class__(**{**cfg.__dict__, "refresh_hz": refresh_hz})
    if context_lines is not None:
        cfg = cfg.__class__(**{**cfg.__dict__, "context_lines": context_lines})
    if no_alt_screen:
        cfg = cfg.__class__(**{**cfg.__dict__, "use_alt_screen": False})

    setup_logging(debug)
    raise typer.Exit(code=watch_loop(cfg, preferred_player=player or cfg.preferred_player, debug=debug))


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
        raise typer.BadParameter("format must be one of: lrc, srt, json")

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
    cache_db = LyricsCache(cfg.cache_db_path)
    
    if clear:
        cache_db.clear()
        typer.echo(f"Cache cleared: {cfg.cache_db_path}")
    else:
        typer.echo("Use --clear to clear the cache")


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
    if not q and not track:
        typer.echo("Error: At least one of --query or --track must be provided", err=True)
        raise typer.Exit(code=1)

    cfg = load_config()
    service = LyricsService(cfg)
    results = service.search(q=q, track_name=track, artist_name=artist, album_name=album)

    if not results:
        typer.echo("No results found")
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
            duration_str = f"{r.duration // 60}:{r.duration % 60:02d}" if r.duration else "?"
            inst_str = " [instrumental]" if r.instrumental else ""
            typer.echo(
                f"{i}. {r.artist_name} - {r.track_name}"
                f" ({duration_str}){inst_str}"
            )
            if r.album_name:
                typer.echo(f"   Album: {r.album_name}")
            typer.echo(f"   Synced: {synced}  Plain: {plain}")
            if r.id:
                typer.echo(f"   ID: {r.id}")
            typer.echo()


def main() -> None:
    app()


if __name__ == "__main__":
    main()

