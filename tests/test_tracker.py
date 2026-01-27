from terminal_lyrics.lrc.model import LyricEvent
from terminal_lyrics.sync.tracker import LineTracker


def test_tracker_changed_only_on_change():
    events = (
        LyricEvent(0, "a"),
        LyricEvent(1000, "b"),
        LyricEvent(2000, "c"),
    )
    tr = LineTracker.from_events(events)
    assert tr.changed_index(0) == 0
    assert tr.changed_index(10) is None
    assert tr.changed_index(999) is None
    assert tr.changed_index(1000) == 1
    assert tr.changed_index(1500) is None
    assert tr.changed_index(2500) == 2

