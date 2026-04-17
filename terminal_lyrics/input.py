"""Keyboard input handler for media controls."""

from __future__ import annotations

import select
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from terminal_lyrics.mpris.client import MprisClient


class MediaControlsHandler:
    """Handles keyboard input for media controls."""

    def __init__(self, client: "MprisClient"):
        self.client = client
        self._enabled = False

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()

    def enter(self) -> None:
        """Set up for non-blocking input (if possible)."""
        # Only enable if stdin is a TTY
        if not sys.stdin.isatty():
            return
        
        # Test if we can actually read in non-blocking mode
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0.01)
            if not ready:
                # stdin is available but not ready - that's OK
                pass
            self._enabled = True
        except (OSError, ValueError):
            # Can't use select on stdin - disable input handling
            self._enabled = False

    def exit(self) -> None:
        """Cleanup."""
        self._enabled = False

    def handle_input(self, timeout: float = 0.01) -> bool:
        """
        Handle keyboard input for media controls.
        
        Returns:
            True if input was handled, False otherwise
        """
        if not self._enabled:
            return False

        # Check if there's input available
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready:
                return False

            # Read with a short timeout to avoid blocking
            import tty
            import termios
            
            # Save and set raw mode temporarily
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                key = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            
            if key == ' ':
                # Space: Play/Pause
                try:
                    self.client.play_pause()
                except Exception:
                    pass
                return True
            elif key == 'n':
                # n: Next track
                try:
                    self.client.next_track()
                except Exception:
                    pass
                return True
            elif key == 'p':
                # p: Previous track
                try:
                    self.client.previous_track()
                except Exception:
                    pass
                return True
            elif key == 's':
                # s: Toggle shuffle
                try:
                    current = self.client.get_shuffle()
                    self.client.set_shuffle(not current)
                except Exception:
                    pass
                return True
            elif key == 'r':
                # r: Cycle repeat mode (None -> Playlist -> Track -> None)
                try:
                    current = self.client.get_loop_status()
                    if current == "None":
                        self.client.set_loop_status("Playlist")
                    elif current == "Playlist":
                        self.client.set_loop_status("Track")
                    else:
                        self.client.set_loop_status("None")
                except Exception:
                    pass
                return True
            elif key == 'l':
                # l: Toggle like
                try:
                    self.client.toggle_like()
                except Exception:
                    pass
                return True
            elif key == 'q':
                # q: Quit (handled by main loop)
                return False
            
            return True
        except Exception:
            return False


def get_key_mapping_help() -> str:
    """Get help text for keyboard shortcuts."""
    return """
Keyboard Shortcuts:
  Space  - Play/Pause
  n      - Next track
  p      - Previous track
  s      - Toggle shuffle
  r      - Cycle repeat mode
  l      - Toggle like
  q      - Quit
    """.strip()
