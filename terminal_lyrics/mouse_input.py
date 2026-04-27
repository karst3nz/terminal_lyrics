"""Mouse click handler for media controls."""

from __future__ import annotations

import logging
import os
import re
import select
import sys
import termios
import threading
import tty
from enum import Enum
from queue import Queue
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from terminal_lyrics.mpris.client import MprisClient

logger = logging.getLogger(__name__)


class MouseProtocol(Enum):
    """Mouse tracking protocol types."""
    X10 = "x10"        # ESC [ M <btn> <x> <y> (legacy, max 223 cols)
    SGR = "sgr"        # ESC [ < btn ; x ; y M|m (modern, unlimited)


class MouseControlsHandler:
    """Handles mouse clicks on media control panel."""

    # Regex for SGR mouse protocol parsing
    # Format: ESC [ < btn ; x ; y M|m
    _SGR_MOUSE_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")

    def __init__(self, client: "MprisClient", rows: int, cols: int, protocol: MouseProtocol = MouseProtocol.SGR):
        self.client = client
        self.rows = rows
        self.cols = cols
        self.protocol = protocol
        self._enabled = False
        self._old_settings = None
        self._reader_thread = None
        self._running = False
        self._event_queue: Queue = Queue()

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()

    def enter(self) -> None:
        """Enable mouse tracking and set up terminal."""
        logger.debug("Attempting to enable mouse tracking (protocol=%s)", self.protocol.value)
        if not sys.stdin.isatty():
            logger.debug("stdin is not a tty, mouse tracking disabled")
            return

        # Save terminal settings
        try:
            self._old_settings = termios.tcgetattr(sys.stdin.fileno())
            logger.debug("Terminal settings saved, fd=%d", sys.stdin.fileno())
        except termios.error as e:
            logger.debug("Failed to get terminal settings: %s", e)
            return

        # Set cbreak mode once - allows reading individual characters
        # but keeps signal handling (Ctrl+C still works)
        try:
            tty.setcbreak(sys.stdin.fileno())
            logger.debug("Terminal set to cbreak mode")
        except termios.error as e:
            logger.debug("Failed to set cbreak mode: %s", e)
            return

        # Enable mouse tracking
        if self.protocol == MouseProtocol.SGR:
            # Enable SGR mouse tracking (mode 1006) - modern terminals like Kitty
            sys.stdout.write("\x1b[?1006h")
            logger.debug("Enabled SGR mouse tracking (mode 1006)")
        # Always enable X10 button tracking (mode 1000) as base
        sys.stdout.write("\x1b[?1000h")
        # Enable all-motion tracking (mode 1003) for hover highlight.
        sys.stdout.write("\x1b[?1003h")
        sys.stdout.flush()
        logger.debug("Enabled mouse tracking modes: 1000, 1003")
        self._enabled = True

        # Start background reader thread
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        logger.debug("Mouse reader thread started")

    def exit(self) -> None:
        """Disable mouse tracking and restore terminal."""
        self._running = False
        if self._reader_thread:
            self._reader_thread.join(timeout=1.0)

        if self._enabled:
            # Disable mouse tracking modes
            if self.protocol == MouseProtocol.SGR:
                sys.stdout.write("\x1b[?1006l")
            sys.stdout.write("\x1b[?1003l")
            sys.stdout.write("\x1b[?1000l")
            sys.stdout.flush()

        # Restore terminal settings
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)
            except termios.error:
                pass

        self._enabled = False

    def _parse_sgr_mouse(self, buf: str) -> dict | None:
        """Parse SGR mouse event sequence.

        Format: ESC [ < btn ; x ; y M|m
        """
        match = self._SGR_MOUSE_RE.search(buf)
        if not match:
            return None

        btn = int(match.group(1))
        x = int(match.group(2))
        y = int(match.group(3))
        suffix = match.group(4)

        # Decode button and modifiers
        button = btn & 0x03  # 0=left, 1=middle, 2=right
        is_release = suffix == "m"
        is_wheel = btn & 0b11000000  # 64=wheel up, 65=wheel down
        is_motion = bool(btn & 0x20) and not is_release and not is_wheel
        wheel_direction = 0
        if is_wheel:
            wheel_direction = -1 if (btn & 0x01) == 0 else 1

        button_names = {0: "left", 1: "middle", 2: "right"}
        btn_name = button_names.get(button, f"unknown({button})")
        event_type = "release" if is_release else ("wheel" if is_wheel else ("motion" if is_motion else "press"))

        # logger.debug(
        #     "Mouse event [SGR]: button=%s(%d) x=%d y=%d event=%s raw_btn=%d suffix=%s",
        #     btn_name, button, x - 1, y - 1, event_type, btn, suffix,
        # )

        return {
            "button": button,
            "x": x - 1,  # Convert to 0-based
            "y": y - 1,  # Convert to 0-based
            "is_release": is_release,
            "is_wheel": bool(is_wheel),
            "is_motion": is_motion,
            "wheel_direction": wheel_direction,  # -1: up, +1: down
        }

    def _parse_x10_mouse(self, buf: str) -> dict | None:
        """Parse X10 mouse event sequence.

        Format: ESC [ M <btn> <x> <y>
        """
        if len(buf) < 6:
            return None

        if buf[0] != "\x1b" or buf[1] != "[" or buf[2] != "M":
            return None

        # Parse button and coordinates
        button_byte = ord(buf[3])
        x_byte = ord(buf[4])
        y_byte = ord(buf[5])

        # Button: 0 = left press, 3 = left release (in X10 mode)
        button = button_byte & 0x03
        is_release = bool(button_byte & 0x20)
        is_wheel = bool(button_byte & 0x40)
        is_motion = bool(button_byte & 0x20) and not is_wheel
        wheel_direction = 0
        if is_wheel:
            wheel_direction = -1 if (button_byte & 0x01) == 0 else 1

        # Convert coordinates (1-based to 0-based)
        x = x_byte - 0x21
        y = y_byte - 0x21

        button_names = {0: "left", 1: "middle", 2: "right"}
        btn_name = button_names.get(button, f"unknown({button})")
        event_type = "release" if is_release else "press"

        # logger.debug(
        #     "Mouse event [X10]: button=%s(%d) x=%d y=%d event=%s raw_byte=%d",
        #     btn_name, button, x, y, event_type, button_byte,
        # )

        return {
            "button": button,
            "x": x,
            "y": y,
            "is_release": is_release,
            "is_wheel": is_wheel,
            "is_motion": is_motion,
            "wheel_direction": wheel_direction,  # -1: up, +1: down
        }

    def _reader_loop(self) -> None:
        """Background thread that continuously reads mouse events from stdin."""
        try:
            fd = sys.stdin.fileno()
        except (OSError, ValueError):
            return

        buf = b""
        while self._running:
            try:
                # Wait for input with short timeout
                ready, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not ready:
                    continue

                raw = os.read(fd, 1)
                if not raw:
                    continue
                buf += raw

                buf_str = buf.decode("latin-1")

                # Try to parse SGR mouse event
                if self.protocol == MouseProtocol.SGR:
                    result = self._parse_sgr_mouse(buf_str)
                    if result:
                        # logger.debug("Mouse event parsed: %s", result)
                        self._event_queue.put(result)
                        buf = b""
                        continue

                # Try to parse X10 mouse event
                if len(buf) >= 6:
                    result = self._parse_x10_mouse(buf_str)
                    if result:
                        # logger.debug("Mouse event parsed (X10): %s", result)
                        self._event_queue.put(result)
                        buf = b""
                        continue

                # If buffer too large, discard
                if len(buf) > 60:
                    logger.debug("Mouse buffer overflow, discarding: %r", buf)
                    buf = b""

            except Exception:
                logger.exception("Error in mouse reader loop")

    def get_event(self) -> dict | None:
        """Get next mouse event from queue (non-blocking)."""
        if self._event_queue.empty():
            return None
        try:
            return self._event_queue.get_nowait()
        except Exception:
            return None

    def check_click(
        self,
        controls_row: int,
        controls_col_start: int,
        controls_col_end: int,
    ) -> str | None:
        """
        Check if there's a mouse click on the controls panel.

        Returns:
            Action string or None
        """
        if not self._enabled or not self._old_settings:
            return None

        # Get mouse event from queue (non-blocking)
        event = self.get_event()
        if not event:
            return None

        logger.debug("check_click: parsed event: button=%d x=%d y=%d release=%s wheel=%s",
                    event["button"], event["x"], event["y"], event["is_release"], event["is_wheel"])

        # Wheel can scroll lyrics even outside the controls row
        if event["is_wheel"]:
            direction = event.get("wheel_direction", 0)
            if direction < 0:
                logger.debug("Mouse wheel up -> scroll_up")
                return "scroll_up"
            if direction > 0:
                logger.debug("Mouse wheel down -> scroll_down")
                return "scroll_down"
            return None

        # Only handle left button press for clickable controls
        if event["button"] != 0 or event["is_release"]:
            btn_type = "release" if event["is_release"] else "wheel" if event["is_wheel"] else f"btn{event['button']}"
            logger.debug(
                "Mouse click ignored: not left press (button=%d, x=%d, y=%d, type=%s)",
                event["button"], event["x"], event["y"], btn_type,
            )
            return None

        x = event["x"]
        y = event["y"]

        logger.debug(
            "Mouse click: button=left x=%d y=%d controls_row=%d col_range=[%d,%d]",
            x, y, controls_row, controls_col_start, controls_col_end,
        )

        # Check if click is on the controls row
        if y != controls_row:
            logger.debug("Mouse click outside controls row (y=%d != controls_row=%d)", y, controls_row)
            return None

        # Check if click is within controls area
        if x < controls_col_start or x > controls_col_end:
            logger.debug("Mouse click outside controls area (x=%d not in [%d,%d])", x, controls_col_start, controls_col_end)
            return None

        # Determine which button was clicked
        controls_width = controls_col_end - controls_col_start
        btn_width = controls_width / 3
        rel_x = x - controls_col_start
        btn_idx = int(rel_x / btn_width)

        actions = ['prev', 'play_pause', 'next']
        if 0 <= btn_idx < len(actions):
            action = actions[btn_idx]
            logger.debug("Mouse click -> action=%s (btn_idx=%d, x=%d, y=%d)", action, btn_idx, x, y)
            return action

        logger.debug("Mouse click on controls row but no zone matched (btn_idx=%d)", btn_idx)
        return None


def get_click_zone_mapping() -> str:
    """Get description of clickable zones."""
    return """
Clickable Zones (left to right):
  Zone 1 - Shuffle toggle
  Zone 2 - Previous track
  Zone 3 - Play/Pause
  Zone 4 - Next track
  Zone 5 - Repeat toggle
  Zone 6 - Like/Favorite
    """.strip()
