from __future__ import annotations

from pathlib import Path

from album2video.config import Config
from album2video import ffmpeg


def normalize_video(input_path: Path, output_path: Path, cfg: Config) -> None:
    """Scale/pad video to output resolution, set fps, strip audio."""
    ow, oh = cfg.output_width, cfg.output_height
    vf = (
        f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
        f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={cfg.output_fps},"
        f"format=yuv420p"
    )
    ffmpeg.run([
        "-i", str(input_path),
        "-vf", vf,
        "-c:v", "libx264",
        "-profile:v", cfg.h264_profile,
        "-level:v", cfg.h264_level,
        "-b:v", cfg.video_bitrate,
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ], desc=f"Normalize: {input_path.name}")
