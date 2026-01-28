from __future__ import annotations

from unittest.mock import Mock, patch

from terminal_lyrics.render.ansi import AnsiRenderer


def test_mocked_render_still_stores_last_args_for_sigwinch():
    """
    If `render` is patched with a mock (as tests often do), we still want the
    renderer to remember what was rendered so SIGWINCH can redraw.
    """
    renderer = AnsiRenderer(use_alt_screen=False)

    with patch.object(renderer, "render") as mock_render:
        renderer.enter()
        renderer.render("T", ["A", "B"], current_idx=0, context_lines=1)

        assert renderer._last_render_args == ("T", ["A", "B"], 0, 1)
        assert mock_render.call_count >= 1

        # Trigger redraw
        assert renderer._resize_handler is not None
        renderer._resize_handler()

        assert mock_render.call_count >= 2
        renderer.exit()

