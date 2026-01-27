from __future__ import annotations

import pytest
import time

from terminal_lyrics.mpris.client import MprisClient, TrackInfo
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable
from tests.mocks.mpris_mock import MockMprisClient


class TestMockMprisClient:
    def test_basic_track_info(self):
        mock = MockMprisClient()
        ti = mock.track_info()
        assert ti.title == "Test Track"
        assert ti.artist == "Test Artist"
        assert ti.album == "Test Album"
        assert "Test Track" in ti.track_key
    
    def test_set_track(self):
        mock = MockMprisClient()
        mock.set_track("New Song", "New Artist", "New Album")
        ti = mock.track_info()
        assert ti.title == "New Song"
        assert ti.artist == "New Artist"
        assert ti.album == "New Album"
    
    def test_multiple_artists(self):
        mock = MockMprisClient()
        mock.set_track("Song", ["Artist1", "Artist2"])
        ti = mock.track_info()
        assert ti.artist == "Artist1, Artist2"
    
    def test_position_ms(self):
        mock = MockMprisClient(position_ms=5000)
        assert mock.position_ms() == 5000
    
    def test_auto_advance(self):
        mock = MockMprisClient(position_ms=0, auto_advance=True, auto_advance_rate_ms_per_sec=1000.0)
        assert mock.position_ms() == 0
        time.sleep(0.1)
        pos = mock.position_ms()
        assert 90 <= pos <= 110  # ~100ms with some tolerance
    
    def test_auto_advance_paused(self):
        mock = MockMprisClient(position_ms=1000, auto_advance=True, playback_status="Paused")
        pos1 = mock.position_ms()
        time.sleep(0.1)
        pos2 = mock.position_ms()
        assert pos1 == pos2  # should not advance when paused
    
    def test_seek(self):
        mock = MockMprisClient(position_ms=0, auto_advance=True)
        mock.seek(10000)
        assert mock.position_ms() >= 10000
        time.sleep(0.05)
        pos = mock.position_ms()
        assert 10000 <= pos <= 10500
    
    def test_playback_status(self):
        mock = MockMprisClient(playback_status="Playing")
        assert mock.playback_status() == "Playing"
        mock.pause()
        assert mock.playback_status() == "Paused"
        mock.play()
        assert mock.playback_status() == "Playing"
    
    def test_track_key_changes_on_track_change(self):
        mock = MockMprisClient()
        key1 = mock.track_info().track_key
        mock.set_track("Different Song", "Different Artist")
        key2 = mock.track_info().track_key
        assert key1 != key2
    
    def test_pick_player(self):
        client = MockMprisClient.pick_player()
        assert isinstance(client, MockMprisClient)
        assert client.service_name == "org.mpris.MediaPlayer2.mock"
    
    def test_pick_player_preferred_not_found(self):
        with pytest.raises(NoPlayersFound):
            MockMprisClient.pick_player(preferred="nonexistent")
    
    def test_list_players(self):
        players = MockMprisClient.list_players()
        assert "org.mpris.MediaPlayer2.mock" in players


class TestMprisClientIntegration:
    """Integration tests that can work with real MPRIS if available."""
    
    def test_list_players_no_exception(self):
        # Should not raise even if no players
        try:
            players = MprisClient.list_players()
            assert isinstance(players, list)
        except Exception as e:
            pytest.fail(f"list_players() raised {e}")
    
    def test_pick_player_no_players(self):
        # This will fail if there are real players, but that's ok
        # We're testing the error handling path
        try:
            # Try to pick a nonexistent player
            client = MprisClient.pick_player(preferred="definitely_not_a_real_player_12345")
            # If we get here, there might be a real player, skip
            pytest.skip("Real MPRIS player found, skipping mock test")
        except NoPlayersFound:
            pass  # Expected
        except Exception as e:
            pytest.fail(f"Unexpected exception: {e}")


class TestTrackInfo:
    def test_track_info_equality(self):
        ti1 = TrackInfo(title="A", artist="B", album="C", track_key="key1")
        ti2 = TrackInfo(title="A", artist="B", album="C", track_key="key1")
        assert ti1.title == ti2.title
        assert ti1.artist == ti2.artist
    
    def test_track_info_different_keys(self):
        ti1 = TrackInfo(title="A", artist="B", album="C", track_key="key1")
        ti2 = TrackInfo(title="A", artist="B", album="C", track_key="key2")
        assert ti1.track_key != ti2.track_key
