from __future__ import annotations

import signal
from unittest.mock import Mock, patch

import pytest

from terminal_lyrics.render.ansi import AnsiRenderer


class TestAnsiRendererSigwinch:
    """Test SIGWINCH handling in renderer."""
    
    def test_sigwinch_registered_on_enter(self):
        """Test that SIGWINCH handler is registered when entering renderer."""
        renderer = AnsiRenderer(use_alt_screen=False)
        
        # Get current handler before enter
        old_handler = signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        signal.signal(signal.SIGWINCH, old_handler)  # restore
        
        renderer.enter()
        
        # Check that handler changed
        current_handler = signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        assert current_handler != old_handler
        signal.signal(signal.SIGWINCH, old_handler)  # restore
        
        renderer.exit()
    
    def test_sigwinch_restored_on_exit(self):
        """Test that SIGWINCH handler is restored to default on exit."""
        renderer = AnsiRenderer(use_alt_screen=False)
        
        old_handler = signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        signal.signal(signal.SIGWINCH, old_handler)  # restore
        
        renderer.enter()
        renderer.exit()
        
        # After exit, handler should be default
        current_handler = signal.signal(signal.SIGWINCH, signal.SIG_DFL)
        assert current_handler == signal.SIG_DFL
        signal.signal(signal.SIGWINCH, old_handler)  # restore
    
    def test_sigwinch_redraws_last_frame(self):
        """SIGWINCH sets a pending flag; the next render() call performs the redraw."""
        renderer = AnsiRenderer(use_alt_screen=False)
        
        with patch.object(renderer, "render") as mock_render:
            renderer.enter()
            
            # Render something
            renderer.render("Test", ["Line 1", "Line 2"], current_idx=0, context_lines=1)
            
            # Verify render was called
            assert mock_render.call_count >= 1
            
            # Simulate SIGWINCH (handler must not call render — avoids reentrant stdout)
            if renderer._resize_handler:
                renderer._resize_handler()
            assert renderer._pending_resize is True
            
            # Next frame from the watch loop invokes render again
            renderer.render("Test", ["Line 1", "Line 2"], current_idx=0, context_lines=1)
            assert mock_render.call_count >= 2
            
            renderer.exit()
    
    def test_last_render_args_stored(self):
        """Test that last render args are stored for SIGWINCH redraw."""
        renderer = AnsiRenderer(use_alt_screen=False)
        renderer.enter()
        
        assert renderer._last_render_args is None
        
        renderer.render("Title", ["A", "B"], current_idx=1, context_lines=1)
        
        assert renderer._last_render_args is not None
        title, lines, idx, ctx = renderer._last_render_args
        assert title == "Title"
        assert lines == ["A", "B"]
        assert idx == 1
        assert ctx == 1
        
        renderer.exit()
        assert renderer._last_render_args is None

    def test_sigwinch_pending_redraw_tail_does_not_reenter_stdout(self):
        """Pending resize is applied after flush, avoiding nested writes to stdout."""
        renderer = AnsiRenderer(use_alt_screen=False)
        renderer.enter()
        with patch("sys.stdout.write"), patch("sys.stdout.flush"):
            renderer._resize_handler()
            assert renderer._pending_resize is True
            renderer.render("T", ["line"], current_idx=0, context_lines=1)
            assert renderer._pending_resize is False
        renderer.exit()
