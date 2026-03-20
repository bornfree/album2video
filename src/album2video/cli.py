from __future__ import annotations

import sys

from album2video.config import load_config
from album2video.scanner import discover_albums, Album
from album2video.assembler import process_album, cleanup_sources


def main() -> None:
    cfg = load_config()
    do_cleanup = cfg.cleanup_sources or "--cleanup-sources" in sys.argv

    print(f"Album root: {cfg.album_root}")
    print(f"Output: {cfg.output_width}x{cfg.output_height} @ {cfg.output_fps}fps, "
          f"H.264 {cfg.h264_profile} {cfg.h264_level}, {cfg.video_bitrate}")
    print(f"Sort: {cfg.sort_order} | Photo duration: {cfg.photo_duration}s | "
          f"Audio crossfade: {cfg.audio_crossfade}s")
    if do_cleanup:
        print("  ** Source cleanup enabled **")
    print()

    albums = discover_albums(cfg.album_root)
    if not albums:
        print("No albums found.")
        return

    _print_albums(albums)

    choice = input("\nSelect album number (or 'a' for all, 'q' to quit): ").strip().lower()
    if choice == "q":
        return
    if choice == "a":
        for album in albums:
            process_album(album, cfg)
            if do_cleanup:
                cleanup_sources(album)
        return

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(albums):
            process_album(albums[idx], cfg)
            if do_cleanup:
                cleanup_sources(albums[idx])
        else:
            print("Invalid selection.")
    except ValueError:
        print("Invalid input.")


def _print_albums(albums: list[Album]) -> None:
    for i, album in enumerate(albums, 1):
        status = " [done]" if album.has_output else ""
        print(f"  {i:>3}. {album.name} "
              f"({len(album.images)} img, {len(album.videos)} vid, "
              f"{len(album.audio)} mp3){status}")
