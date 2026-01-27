
"""
Compatibility entrypoint.

The project has been refactored into the `terminal_lyrics` package.
Prefer running:
  - `terminal-lyrics watch`
or:
  - `python -m terminal_lyrics`
"""

from terminal_lyrics.cli import main as cli_main


def cli() -> None:
    cli_main()


if __name__ == "__main__":
    cli()