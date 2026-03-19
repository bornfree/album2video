from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from album2video.config import IMAGE_EXTS, VIDEO_EXTS, AUDIO_EXTS


@dataclass
class Album:
    name: str
    path: Path
    images: list[Path] = field(default_factory=list)
    videos: list[Path] = field(default_factory=list)
    audio: list[Path] = field(default_factory=list)

    @property
    def media_count(self) -> int:
        return len(self.images) + len(self.videos)

    @property
    def has_output(self) -> bool:
        return (self.path / "__video.mp4").exists()


def discover_albums(root: Path) -> list[Album]:
    if not root.is_dir():
        raise SystemExit(f"ALBUM_ROOT does not exist: {root}")
    albums: list[Album] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        album = scan_album(entry)
        if album.media_count > 0:
            albums.append(album)
    return albums


def scan_album(folder: Path) -> Album:
    album = Album(name=folder.name, path=folder)
    for f in folder.iterdir():
        if f.name.startswith(".") or f.name == "__video.mp4":
            continue
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            album.images.append(f)
        elif ext in VIDEO_EXTS:
            album.videos.append(f)
        elif ext in AUDIO_EXTS:
            album.audio.append(f)
    return album
