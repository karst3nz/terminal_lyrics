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

        # prefer Playing
        for s in players:
            try:
                c = MprisClient(s)
                status = c.playback_status()
                if status.lower() == "playing":
                    return c
            except Exception:
                continue

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
        key = " | ".join(x for x in (artist, title, album, url, track_id) if x)
        return TrackInfo(title=title, artist=artist, album=album, track_key=key)

