from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Callable, TypeVar

from .client import MprisClient, TrackInfo

T = TypeVar("T")

_executor: concurrent.futures.ThreadPoolExecutor | None = None


def _dbus_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="tl-mpris-dbus"
        )
    return _executor


async def run_mpris(fn: Callable[[], T]) -> T:
    """Run a blocking dbus-python call on a single worker thread (session bus is not thread-safe)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_dbus_executor(), fn)


async def pick_player_service_name(preferred: str | None) -> str:
    def _run() -> str:
        return MprisClient.pick_player(preferred).service_name

    return await run_mpris(_run)


async def probe_player(service_name: str) -> None:
    """Verify the player bus name is still reachable (constructor may raise)."""

    def _run() -> None:
        MprisClient(service_name)

    await run_mpris(_run)


async def track_info(service_name: str) -> TrackInfo:
    return await run_mpris(lambda: MprisClient(service_name).track_info())


async def position_ms(service_name: str) -> int:
    return await run_mpris(lambda: MprisClient(service_name).position_ms())


async def playback_status(service_name: str) -> str:
    return await run_mpris(lambda: MprisClient(service_name).playback_status())


async def previous_track(service_name: str) -> None:
    await run_mpris(lambda: MprisClient(service_name).previous_track())


async def play_pause(service_name: str) -> None:
    await run_mpris(lambda: MprisClient(service_name).play_pause())


async def next_track(service_name: str) -> None:
    await run_mpris(lambda: MprisClient(service_name).next_track())


async def seek_ms(service_name: str, position_ms: int) -> None:
    await run_mpris(lambda: MprisClient(service_name).seek_ms(position_ms))


async def list_players() -> list[str]:
    return await run_mpris(MprisClient.list_players)


def shutdown_mpris_executor() -> None:
    global _executor
    ex = _executor
    _executor = None
    if ex is not None:
        ex.shutdown(wait=True, cancel_futures=False)
