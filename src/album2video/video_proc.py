from __future__ import annotations

from pathlib import Path

from album2video.config import Config
from album2video import ffmpeg


def normalize_video(input_path: Path, output_path: Path, cfg: Config) -> None:
    """Scale/pad video to output resolution, set fps, strip audio.

    Portrait videos get a blurred background fill instead of black bars.
    """
    ow, oh = cfg.output_width, cfg.output_height
    w, h = ffmpeg.probe_dimensions(input_path)
    is_portrait = h > w

    if is_portrait:
        # Split → blurred bg (scale-to-fill + crop + blur) + sharp fg (fit-to-height)
        # overlay fg centered on bg
        vf = (
            f"split[bg][fg];"
            f"[bg]scale={ow}:{oh}:force_original_aspect_ratio=increase,"
            f"crop={ow}:{oh},boxblur=40:5[bg_blur];"
            f"[fg]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,"
            f"fps={cfg.output_fps},format=yuv420p"
        )
    else:
        vf = (
            f"scale={ow}:{oh}:force_original_aspect_ratio=decrease,"
            f"pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={cfg.output_fps},"
            f"format=yuv420p"
        )

    ffmpeg.run([
        "-i", str(input_path),
        "-filter_complex" if is_portrait else "-vf", vf,
        "-c:v", "libx264",
        "-profile:v", cfg.h264_profile,
        "-level:v", cfg.h264_level,
        "-b:v", cfg.video_bitrate,
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ], desc=f"Normalize: {input_path.name}")
