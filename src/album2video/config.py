from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

IMAGE_EXTS = frozenset(
    {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif",
     ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf"}
)
VIDEO_EXTS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts"})
AUDIO_EXTS = frozenset({".mp3"})


@dataclass(frozen=True)
class Config:
    album_root: Path
    output_width: int = 3840
    output_height: int = 2160
    output_fps: int = 30
    video_bitrate: str = "20M"
    h264_profile: str = "high"
    h264_level: str = "5.1"
    audio_bitrate: str = "192k"
    sort_order: str = "date"
    photo_duration: int = 10
    audio_crossfade: int = 3
    ken_burns: bool = True

    @property
    def resolution(self) -> str:
        return f"{self.output_width}:{self.output_height}"


def load_config() -> Config:
    load_dotenv()
    root = os.getenv("ALBUM_ROOT")
    if not root:
        raise SystemExit("ALBUM_ROOT not set in .env or environment")
    return Config(
        album_root=Path(root).expanduser().resolve(),
        output_width=int(os.getenv("OUTPUT_WIDTH", "3840")),
        output_height=int(os.getenv("OUTPUT_HEIGHT", "2160")),
        output_fps=int(os.getenv("OUTPUT_FPS", "30")),
        video_bitrate=os.getenv("VIDEO_BITRATE", "20M"),
        h264_profile=os.getenv("H264_PROFILE", "high"),
        h264_level=os.getenv("H264_LEVEL", "5.1"),
        audio_bitrate=os.getenv("AUDIO_BITRATE", "192k"),
        sort_order=os.getenv("SORT_ORDER", "date"),
        photo_duration=int(os.getenv("PHOTO_DURATION", "10")),
        audio_crossfade=int(os.getenv("AUDIO_CROSSFADE", "3")),
        ken_burns=os.getenv("KEN_BURNS", "true").lower() in ("true", "1", "yes"),
    )
