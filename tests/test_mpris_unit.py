from __future__ import annotations

import types

import pytest

import terminal_lyrics.mpris.client as mpris_client
from terminal_lyrics.mpris.client import MprisClient, _join_artist


def test_list_players_returns_empty_on_dbus_error(monkeypatch):
    class _FakeDbusException(Exception):
        pass

    def _raise_session_bus():
        raise _FakeDbusException("no session bus")

    # Patch the imported `dbus` module inside `terminal_lyrics.mpris.client`
    monkeypatch.setattr(mpris_client, "dbus", types.SimpleNamespace(SessionBus=_raise_session_bus, DBusException=_FakeDbusException))

    assert MprisClient.list_players() == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (["A", "B"], "A, B"),
        (("A", "", "B"), "A, B"),
        ("Solo", "Solo"),
        (123, "123"),
        (None, "None"),
    ],
)
def test_join_artist_handles_common_types(value, expected):
    assert _join_artist(value) == expected


def test_join_artist_filters_unstringable_values(monkeypatch):
    class BadStr:
        def __str__(self):
            raise RuntimeError("nope")

    assert _join_artist([BadStr(), "OK"]) == "OK"

