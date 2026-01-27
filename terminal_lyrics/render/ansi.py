from __future__ import annotations

import shutil
import signal
import sys
from dataclasses import dataclass
from typing import Callable


CSI = "\x1b["


def _sgr(*codes: int) -> str:
    return CSI + ";".join(str(c) for c in codes) + "m"


@dataclass(frozen=True, slots=True)
class Theme:
    title: str = _sgr(36, 1)  # cyan bold
    current: str = _sgr(32, 1)  # green bold
    dim: str = _sgr(90)  # bright black
    warning: str = _sgr(33, 1)  # yellow bold
    reset: str = _sgr(0)


class AnsiRenderer:
    def __init__(self, use_alt_screen: bool = True, theme: Theme | None = None):
        self.use_alt_screen = use_alt_screen
        self.theme = theme or Theme()
        self._entered = False
        self._resize_handler: Callable[[], None] | None = None
        self._last_render_args: tuple[str, list[str], int, int] | None = None

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.exit()

    def enter(self) -> None:
        if self._entered:
            return
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049h")  # alt screen
        sys.stdout.write(CSI + "?25l")  # hide cursor
        sys.stdout.write(CSI + "H" + CSI + "2J")  # home + clear
        sys.stdout.flush()
        self._entered = True
        
        # Register SIGWINCH handler for resize
        def _on_resize(signum, frame):
            if self._last_render_args:
                title, lines, current_idx, context_lines = self._last_render_args
                self.render(title, lines, current_idx, context_lines)
        
        self._resize_handler = _on_resize
        signal.signal(signal.SIGWINCH, _on_resize)

    def exit(self) -> None:
        if not self._entered:
            return
        # Restore default SIGWINCH handler
        if self._resize_handler:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL)
            self._resize_handler = None
        sys.stdout.write(self.theme.reset)
        sys.stdout.write(CSI + "?25h")  # show cursor
        if self.use_alt_screen:
            sys.stdout.write(CSI + "?1049l")  # normal screen
        sys.stdout.flush()
        self._entered = False
        self._last_render_args = None

    def render(
        self,
        title: str,
        lines: list[str],
        current_idx: int,
        context_lines: int = 1,
    ) -> None:
        # Store args for SIGWINCH redraw
        self._last_render_args = (title, lines, current_idx, context_lines)
        
        cols, rows = shutil.get_terminal_size(fallback=(80, 24))
        # reserve 1 line for title
        body_rows = max(rows - 1, 1)

        # window around current line, but keep within list
        if current_idx < 0:
            start = 0
        else:
            start = max(current_idx - context_lines, 0)
        end = min(start + body_rows, len(lines))
        start = max(end - body_rows, 0)

        out: list[str] = []
        out.append(f"{self.theme.title}♫ {title} ♫{self.theme.reset}")

        for i in range(start, end):
            t = lines[i]
            if i == current_idx:
                out.append(f"{self.theme.current}{t}{self.theme.reset}")
            else:
                out.append(f"{self.theme.dim}{t}{self.theme.reset}")

        # move home + clear, then print full frame
        sys.stdout.write(CSI + "H" + CSI + "2J")
        sys.stdout.write("\n".join(out))
        sys.stdout.write(self.theme.reset)
        sys.stdout.flush()

