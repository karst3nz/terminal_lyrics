from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import dbus

from .errors import NoPlayersFound, PlayerUnavailable

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrackInfo:
    title: str
    artist: str
    album: str
    # stable-ish identifier for "track changed" checks
    track_key: str
    length_ms: int = 0


def _to_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return ""


def _join_artist(value: Any) -> str:
    if isinstance(value, (list, tuple, dbus.Array)):
        return ", ".join(_to_str(x) for x in value if _to_str(x))
    return _to_str(value)


class MprisClient:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self._bus = dbus.SessionBus()
        self._obj = self._bus.get_object(service_name, "/org/mpris/MediaPlayer2")
        self._props = dbus.Interface(self._obj, "org.freedesktop.DBus.Properties")

    @staticmethod
    def list_players() -> list[str]:
        try:
            bus = dbus.SessionBus()
            return [s for s in bus.list_names() if s.startswith("org.mpris.MediaPlayer2.")]
        except dbus.DBusException as e:
            # In restricted environments (tests/sandbox/CI), connecting to the
            # session bus can fail (e.g. AccessDenied). Treat as "no players".
            logger.debug("Unable to connect to D-Bus session bus: %s", e)
            return []

    @staticmethod
    def pick_player(preferred: str | None = None) -> "MprisClient":
        players = MprisClient.list_players()
        if not players:
            raise NoPlayersFound("No active MPRIS players")

        if preferred:
            # allow passing short name like "vlc"
            for s in players:
                if s == preferred or s.endswith("." + preferred):
                    return MprisClient(s)
            logger.warning("Preferred player '%s' not found, falling back", preferred)

        # prefer Playing, then Paused, then any player
        paused_fallback = None
        for s in players:
            try:
                c = MprisClient(s)
                status = c.playback_status()
                if status.lower() == "playing":
                    return c
                if status.lower() == "paused" and paused_fallback is None:
                    paused_fallback = c
            except Exception:
                continue

        # Return paused player if available, otherwise first player
        if paused_fallback:
            return paused_fallback
        return MprisClient(players[0])

    def playback_status(self) -> str:
        try:
            return _to_str(self._props.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus"))
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def metadata(self) -> dict[str, Any]:
        try:
            md = self._props.Get("org.mpris.MediaPlayer2.Player", "Metadata")
            # dbus.Dictionary acts like dict
            return dict(md)
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def position_ms(self) -> int:
        """
        MPRIS Position is microseconds.
        """
        try:
            pos_us = self._props.Get("org.mpris.MediaPlayer2.Player", "Position")
            return int(pos_us) // 1000
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def track_info(self) -> TrackInfo:
        md = self.metadata()
        title = _to_str(md.get("xesam:title", "")) or ""
        artist = _join_artist(md.get("xesam:artist", [])) or ""
        album = _to_str(md.get("xesam:album", "")) or ""
        url = _to_str(md.get("xesam:url", "")) or ""
        track_id = _to_str(md.get("mpris:trackid", "")) or ""

        # Get track length in microseconds, convert to milliseconds
        length_us = md.get("mpris:length", 0)
        try:
            length_ms = int(length_us) // 1000
        except (ValueError, TypeError):
            length_ms = 0

        key = " | ".join(x for x in (artist, title, album, url, track_id) if x)
        return TrackInfo(
            title=title, artist=artist, album=album, track_key=key, length_ms=length_ms
        )

    # --- Media control methods ---

    def play_pause(self) -> None:
        """Toggle play/pause."""
        try:
            iface = dbus.Interface(self._obj, "org.mpris.MediaPlayer2.Player")
            iface.PlayPause()
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def previous_track(self) -> None:
        """Skip to previous track."""
        try:
            iface = dbus.Interface(self._obj, "org.mpris.MediaPlayer2.Player")
            iface.Previous()
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def next_track(self) -> None:
        """Skip to next track."""
        try:
            iface = dbus.Interface(self._obj, "org.mpris.MediaPlayer2.Player")
            iface.Next()
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def get_shuffle(self) -> bool:
        """Get shuffle status."""
        try:
            return bool(self._props.Get("org.mpris.MediaPlayer2.Player", "Shuffle"))
        except dbus.DBusException:
            return False

    def set_shuffle(self, value: bool) -> None:
        """Set shuffle status."""
        try:
            self._props.Set("org.mpris.MediaPlayer2.Player", "Shuffle", dbus.Boolean(value))
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def get_loop_status(self) -> str:
        """Get loop/repeat status: 'None', 'Playlist', or 'Track'."""
        try:
            return _to_str(self._props.Get("org.mpris.MediaPlayer2.Player", "LoopStatus"))
        except dbus.DBusException:
            return "None"

    def set_loop_status(self, status: str) -> None:
        """Set loop/repeat status: 'None', 'Playlist', or 'Track'."""
        try:
            self._props.Set("org.mpris.MediaPlayer2.Player", "LoopStatus", dbus.String(status))
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e

    def toggle_like(self) -> None:
        """Toggle favorite/like status if supported."""
        # MPRIS doesn't have a standard 'like' method, so this is a no-op
        # Some players support 'org.mpris.MediaPlayer2.Player.SetPosition' or custom interfaces
        logger.debug("toggle_like: not supported by standard MPRIS")
        pass

    def seek_ms(self, position_ms: int) -> None:
        """Seek to absolute position in milliseconds."""
        if position_ms < 0:
            position_ms = 0

        can_seek = True
        try:
            can_seek = bool(self._props.Get("org.mpris.MediaPlayer2.Player", "CanSeek"))
        except dbus.DBusException:
            # Some players do not expose CanSeek consistently; try anyway.
            can_seek = True
        if not can_seek:
            raise PlayerUnavailable("Player does not support seeking (CanSeek=false)")

        current_ms = 0
        try:
            current_ms = self.position_ms()
        except PlayerUnavailable:
            current_ms = 0

        set_position_ok = False
        try:
            iface = dbus.Interface(self._obj, "org.mpris.MediaPlayer2.Player")
            md = self.metadata()
            track_id = md.get("mpris:trackid")
            if track_id:
                iface.SetPosition(track_id, dbus.Int64(int(position_ms) * 1000))
                set_position_ok = True
        except dbus.DBusException as e:
            # Fall back to relative seek below for players that don't support SetPosition
            logger.debug("SetPosition failed, fallback to Seek: %s", e)

        # Some players accept SetPosition call but ignore it. Verify and fallback to Seek.
        if set_position_ok:
            try:
                updated_ms = self.position_ms()
                # Consider seek successful when we're close enough (buffering/rounding tolerance).
                if abs(updated_ms - int(position_ms)) <= 1500:
                    return
                current_ms = updated_ms
            except PlayerUnavailable:
                # Could not verify, continue with best-effort fallback.
                pass

        try:
            iface = dbus.Interface(self._obj, "org.mpris.MediaPlayer2.Player")
            delta_us = (int(position_ms) - int(current_ms)) * 1000
            iface.Seek(dbus.Int64(delta_us))
        except dbus.DBusException as e:
            raise PlayerUnavailable(str(e)) from e
