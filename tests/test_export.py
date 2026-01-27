from terminal_lyrics.lrc.export import export_srt
from terminal_lyrics.lrc.model import LrcDocument, LyricEvent


def test_export_srt_basic():
    doc = LrcDocument(events=(LyricEvent(0, "a"), LyricEvent(1000, "b")))
    srt = export_srt(doc, last_line_duration_ms=2000)
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "00:00:01,000 --> 00:00:03,000" in srt
    assert "\na\n" in srt
    assert "\nb\n" in srt

