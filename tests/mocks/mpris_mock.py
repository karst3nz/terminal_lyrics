from __future__ import annotations

from typing import Any
import time

from terminal_lyrics.mpris.client import TrackInfo
from terminal_lyrics.mpris.errors import NoPlayersFound


class MockMprisClient:
    """
    Mock MPRIS client for testing.
    
    Simulates a player with controllable state:
    - playback_status: "Playing", "Paused", "Stopped"
    - metadata: track info dict
    - position_ms: current position (can be auto-incremented)
    """
    
    def __init__(
        self,
        service_name: str = "org.mpris.MediaPlayer2.mock",
        playback_status: str = "Playing",
        metadata: dict[str, Any] | None = None,
        position_ms: int = 0,
        auto_advance: bool = False,
        auto_advance_rate_ms_per_sec: float = 1000.0,
    ):
        self.service_name = service_name
        self.auto_advance = auto_advance
        self.auto_advance_rate_ms_per_sec = float(auto_advance_rate_ms_per_sec)

        self._start_time: float | None = None
        self._playback_status = playback_status
        self._position_ms = int(position_ms)
        self._metadata: dict[str, Any] = dict(metadata) if metadata else {
            "xesam:title": "Test Track",
            "xesam:artist": ["Test Artist"],
            "xesam:album": "Test Album",
            "xesam:url": "file:///test.mp3",
            "mpris:trackid": "/org/mpris/MediaPlayer2/Track/1",
        }
    
    def _update_position(self) -> None:
        if self.auto_advance and self._playback_status.lower() == "playing":
            if self._start_time is None:
                self._start_time = time.time()
            elapsed = time.time() - self._start_time
            self._position_ms = int(elapsed * self.auto_advance_rate_ms_per_sec)
    
    @staticmethod
    def list_players() -> list[str]:
        return ["org.mpris.MediaPlayer2.mock"]
    
    @staticmethod
    def pick_player(preferred: str | None = None) -> MockMprisClient:
        if preferred and preferred != "mock":
            raise NoPlayersFound(f"Preferred player '{preferred}' not found")
        return MockMprisClient()
    
    def playback_status(self) -> str:
        return self._playback_status
    
    def metadata(self) -> dict[str, Any]:
        return self._metadata.copy()
    
    def position_ms(self) -> int:
        self._update_position()
        return self._position_ms
    
    def track_info(self) -> TrackInfo:
        md = self.metadata()
        title = str(md.get("xesam:title", "")) or ""
        artist_list = md.get("xesam:artist", [])
        if isinstance(artist_list, (list, tuple)):
            artist = ", ".join(str(x) for x in artist_list if str(x))
        else:
            artist = str(artist_list) or ""
        album = str(md.get("xesam:album", "")) or ""
        url = str(md.get("xesam:url", "")) or ""
        track_id = str(md.get("mpris:trackid", "")) or ""
        key = " | ".join(x for x in (artist, title, album, url, track_id) if x)
        return TrackInfo(title=title, artist=artist, album=album, track_key=key)
    
    def set_track(self, title: str, artist: str | list[str], album: str = "") -> None:
        """Helper to set track metadata."""
        if isinstance(artist, str):
            artist_list = [artist]
        else:
            artist_list = artist
        self._metadata.update({
            "xesam:title": title,
            "xesam:artist": artist_list,
            "xesam:album": album,
            "mpris:trackid": f"/org/mpris/MediaPlayer2/Track/{hash((title, tuple(artist_list), album))}",
        })
    
    def seek(self, position_ms: int) -> None:
        """Seek to position."""
        self._position_ms = max(0, int(position_ms))
        self._start_time = time.time() - (position_ms / self.auto_advance_rate_ms_per_sec)
    
    def pause(self) -> None:
        """Pause playback."""
        self._update_position()
        self._playback_status = "Paused"
    
    def play(self) -> None:
        """Resume playback."""
        self._update_position()
        self._playback_status = "Playing"
        if self._start_time is None:
            self._start_time = time.time() - (self._position_ms / self.auto_advance_rate_ms_per_sec)
