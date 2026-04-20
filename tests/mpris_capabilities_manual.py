"""
Comprehensive test script for all MPRIS capabilities.

Run with: python tests/mpris_capabilities_manual.py
"""

from __future__ import annotations

import sys
import time
from typing import Any

from terminal_lyrics.mpris.client import MprisClient, TrackInfo
from terminal_lyrics.mpris.errors import NoPlayersFound, PlayerUnavailable


def print_header(title: str):
    """Print a formatted test header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_subheader(title: str):
    """Print a formatted sub-test header."""
    print(f"\n  ┌─ {title}")
    print(f"  ├{'─'*58}")


def print_result(label: str, value: Any, status: str = "✓"):
    """Print a test result."""
    print(f"  │ {status} {label}: {value}")


def print_error(label: str, error: str):
    """Print a test error."""
    print(f"  │ ✗ {label}: {error}")


def test_player_discovery(client: MprisClient):
    """Test player discovery and basic info."""
    print_subheader("1. Player Discovery")
    
    # Test list_players
    players = MprisClient.list_players()
    print_result("Available players", f"{len(players)} found")
    for i, p in enumerate(players, 1):
        print(f"  │   {i}. {p}")
    
    # Test service name
    print_result("Connected to", client.service_name)
    
    return len(players) > 0


def test_playback_control(client: MprisClient):
    """Test playback control methods."""
    print_subheader("2. Playback Control")
    
    # Get initial status
    try:
        status = client.playback_status()
        print_result("Initial status", status)
    except PlayerUnavailable as e:
        print_error("Playback status", str(e))
        return
    
    # Test play/pause
    print("\n  │ Testing play/pause toggle...")
    try:
        client.play_pause()
        time.sleep(0.5)
        new_status = client.playback_status()
        print_result("After play_pause()", new_status)
        
        # Toggle back
        client.play_pause()
        time.sleep(0.5)
        final_status = client.playback_status()
        print_result("After second play_pause()", final_status)
    except PlayerUnavailable as e:
        print_error("play_pause", str(e))
    
    # Test explicit play
    print("\n  │ Testing explicit play...")
    try:
        client.play()
        time.sleep(0.5)
        status = client.playback_status()
        print_result("After play()", status)
    except PlayerUnavailable as e:
        print_error("play", str(e))
    
    # Test explicit pause
    print("\n  │ Testing explicit pause...")
    try:
        client.pause()
        time.sleep(0.5)
        status = client.playback_status()
        print_result("After pause()", status)
    except PlayerUnavailable as e:
        print_error("pause", str(e))


def test_track_navigation(client: MprisClient):
    """Test track navigation methods."""
    print_subheader("3. Track Navigation")
    
    # Get current track
    try:
        info = client.track_info()
        print_result("Current track", f"{info.artist} - {info.title}")
        print_result("Album", info.album)
        print_result("Duration", f"{info.length_ms // 1000}s")
    except PlayerUnavailable as e:
        print_error("track_info", str(e))
        return
    
    # Test next track
    print("\n  │ Testing next track...")
    try:
        client.next_track()
        time.sleep(1)
        info = client.track_info()
        print_result("After next()", f"{info.artist} - {info.title}")
    except PlayerUnavailable as e:
        print_error("next_track", str(e))
    
    # Test previous track
    print("\n  │ Testing previous track...")
    try:
        client.previous_track()
        time.sleep(1)
        info = client.track_info()
        print_result("After previous()", f"{info.artist} - {info.title}")
    except PlayerUnavailable as e:
        print_error("previous_track", str(e))


def test_position_tracking(client: MprisClient):
    """Test position tracking."""
    print_subheader("4. Position Tracking")
    
    try:
        pos1 = client.position_ms()
        print_result("Position (now)", f"{pos1 // 1000}s")
        
        time.sleep(2)
        
        pos2 = client.position_ms()
        print_result("Position (+2s)", f"{pos2 // 1000}s")
        
        diff = (pos2 - pos1) // 1000
        print_result("Elapsed time", f"{diff}s (expected ~2s)")
        
        if abs(diff - 2) <= 1:
            print_result("Position tracking accuracy", "OK")
        else:
            print_result("Position tracking accuracy", f"Off by {diff - 2}s")
    except PlayerUnavailable as e:
        print_error("position_ms", str(e))


def test_metadata_inspection(client: MprisClient):
    """Test metadata retrieval and parsing."""
    print_subheader("5. Metadata Inspection")
    
    try:
        md = client.metadata()
        
        print_result("Total metadata keys", len(md))
        print("\n  │ Metadata fields:")
        
        # Print all metadata fields
        for key in sorted(md.keys()):
            value = md[key]
            if isinstance(value, dict):
                print(f"  │   {key}: {{...}}")
            elif isinstance(value, (list, tuple)):
                print(f"  │   {key}: [{', '.join(str(v) for v in value)}]")
            else:
                print(f"  │   {key}: {value}")
        
        # Test track_info parsing
        info = client.track_info()
        print("\n  │ Parsed TrackInfo:")
        print_result("title", info.title)
        print_result("artist", info.artist)
        print_result("album", info.album)
        print_result("track_key", info.track_key[:50] + "..." if len(info.track_key) > 50 else info.track_key)
        print_result("length_ms", info.length_ms)
        
    except PlayerUnavailable as e:
        print_error("metadata", str(e))


def test_shuffle_control(client: MprisClient):
    """Test shuffle control."""
    print_subheader("6. Shuffle Control")
    
    try:
        # Get current state
        initial = client.get_shuffle()
        print_result("Initial shuffle", str(initial))
        
        # Toggle shuffle
        print("\n  │ Toggling shuffle...")
        client.set_shuffle(not initial)
        time.sleep(0.3)
        new_state = client.get_shuffle()
        print_result("After toggle", str(new_state))
        
        # Toggle back
        client.set_shuffle(initial)
        time.sleep(0.3)
        final_state = client.get_shuffle()
        print_result("Restored", str(final_state))
        
        if final_state == initial:
            print_result("Shuffle toggle test", "PASSED")
        else:
            print_result("Shuffle toggle test", "FAILED (state changed)")
            
    except PlayerUnavailable as e:
        print_error("shuffle", str(e))


def test_loop_control(client: MprisClient):
    """Test loop/repeat control."""
    print_subheader("7. Loop/Repeat Control")
    
    try:
        # Get current state
        initial = client.get_loop_status()
        print_result("Initial loop status", initial)
        
        # Test cycling through loop modes
        modes = ["None", "Playlist", "Track"]
        
        for mode in modes:
            print(f"\n  │ Setting loop to: {mode}")
            try:
                client.set_loop_status(mode)
                time.sleep(0.3)
                actual = client.get_loop_status()
                print_result(f"Actual status", actual)
                
                if actual == mode:
                    print_result(f"Set '{mode}' test", "PASSED")
                else:
                    print_result(f"Set '{mode}' test", f"EXPECTED {mode}, GOT {actual}")
            except PlayerUnavailable as e:
                print_error(f"set_loop_status('{mode}')", str(e))
        
        # Restore initial state
        print(f"\n  │ Restoring to: {initial}")
        client.set_loop_status(initial)
        time.sleep(0.3)
        final = client.get_loop_status()
        print_result("Restored", final)
        
    except PlayerUnavailable as e:
        print_error("loop_status", str(e))


def test_volume_control(client: MprisClient):
    """Test volume control."""
    print_subheader("8. Volume Control")
    
    try:
        # Get current volume
        initial = client.get_volume()
        print_result("Initial volume", f"{initial:.2f} ({initial*100:.0f}%)")
        
        # Test setting volume to different values
        test_volumes = [0.5, 0.8, 0.2, initial]
        
        for vol in test_volumes:
            print(f"\n  │ Setting volume to: {vol:.2f} ({vol*100:.0f}%)")
            try:
                client.set_volume(vol)
                time.sleep(0.3)
                actual = client.get_volume()
                print_result("Actual volume", f"{actual:.2f} ({actual*100:.0f}%)")
                
                # Allow some tolerance
                if abs(actual - vol) < 0.05:
                    print_result(f"Set {vol:.2f} test", "PASSED")
                else:
                    print_result(f"Set {vol:.2f} test", f"EXPECTED {vol:.2f}, GOT {actual:.2f}")
            except PlayerUnavailable as e:
                print_error(f"set_volume({vol})", str(e))
        
    except PlayerUnavailable as e:
        print_error("volume", str(e))


def test_like_status(client: MprisClient):
    """Test like/favorite status."""
    print_subheader("9. Like/Favorite Status")
    
    try:
        liked = client.get_like_status()
        print_result("Like status", "♥ Liked" if liked else "♡ Not liked")
        print_result("Note", "Support depends on player implementation")
    except PlayerUnavailable as e:
        print_error("like_status", str(e))


def test_stop(client: MprisClient):
    """Test stop functionality."""
    print_subheader("10. Stop Functionality")
    
    try:
        print("  │ ⚠  WARNING: This will stop playback!")
        print("  │ Press Ctrl+C to skip this test")
        time.sleep(2)
        
        client.stop()
        time.sleep(0.5)
        status = client.playback_status()
        print_result("After stop()", status)
        
        if status.lower() == "stopped":
            print_result("Stop test", "PASSED")
        else:
            print_result("Stop test", f"Status is '{status}' (expected 'Stopped')")
            
    except KeyboardInterrupt:
        print("\n  │   Stop test skipped by user")
    except PlayerUnavailable as e:
        print_error("stop", str(e))


def run_all_tests(preferred_player: str | None = None):
    """Run all MPRIS capability tests."""
    print_header("MPRIS Capability Tests")
    print("Testing all MPRIS v2 interface methods\n")
    
    # Player discovery
    try:
        client = MprisClient.pick_player(preferred=preferred_player)
        quit(0)
    except NoPlayersFound:
        print("✗ No MPRIS players found!")
        print("  Make sure a music player is running.")
        return 1
    
    print(f"✓ Connected to: {client.service_name}\n")
    
    # Run all tests
    tests = [
        ("Player Discovery", lambda: test_player_discovery(client)),
        ("Playback Control", lambda: test_playback_control(client)),
        ("Track Navigation", lambda: test_track_navigation(client)),
        ("Position Tracking", lambda: test_position_tracking(client)),
        ("Metadata Inspection", lambda: test_metadata_inspection(client)),
        ("Shuffle Control", lambda: test_shuffle_control(client)),
        ("Loop/Repeat Control", lambda: test_loop_control(client)),
        ("Volume Control", lambda: test_volume_control(client)),
        ("Like/Favorite Status", lambda: test_like_status(client)),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            print_header(f"Test: {test_name}")
            test_func()
            results.append((test_name, True, None))
        except KeyboardInterrupt:
            print("\n\n⚠  Test interrupted by user")
            results.append((test_name, False, "Interrupted"))
            break
        except Exception as e:
            print(f"\n✗ Test failed with exception: {e}")
            results.append((test_name, False, str(e)))
    
    # Print summary
    print_header("Test Summary")
    
    passed = sum(1 for _, success, _ in results if success)
    failed = sum(1 for _, success, _ in results if not success)
    
    print(f"\n  Total tests: {len(results)}")
    print(f"  ✓ Passed: {passed}")
    print(f"  ✗ Failed: {failed}")
    
    if failed > 0:
        print("\n  Failed tests:")
        for name, success, error in results:
            if not success:
                print(f"    - {name}: {error}")
    
    print()
    return 0 if failed == 0 else 1


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test all MPRIS capabilities")
    parser.add_argument(
        "--player",
        type=str,
        default=None,
        help="Preferred player name (e.g., vlc, spotify)",
    )
    
    args = parser.parse_args()
    
    try:
        exit_code = run_all_tests(preferred_player=args.player)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠  Tests interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
