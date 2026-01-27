from terminal_lyrics.lrc.parse import parse_lrc


def test_parse_multiple_timestamps():
    doc = parse_lrc("[00:01.00][00:02.5]hey\n")
    assert [e.t_ms for e in doc.events] == [1000, 2500]
    assert [e.text for e in doc.events] == ["hey", "hey"]


def test_parse_offset_clamped():
    doc = parse_lrc("[offset:-1500]\n[00:01.00]x\n")
    assert doc.offset_ms == -1500
    assert doc.events[0].t_ms == 0


