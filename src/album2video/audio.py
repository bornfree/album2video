from __future__ import annotations

from pathlib import Path

from album2video.config import Config
from album2video import ffmpeg


def build_soundtrack(mp3_files: list[Path], video_duration: float, output_path: Path, cfg: Config) -> None:
    """Crossfade-concatenate MP3s, loop/trim to video duration, encode as MP3."""
    if not mp3_files:
        return

    if len(mp3_files) == 1:
        _loop_and_trim(mp3_files[0], video_duration, output_path, cfg)
        return

    # Build crossfade filter chain for multiple MP3s
    crossfade_dur = cfg.audio_crossfade
    inputs: list[str] = []
    for f in mp3_files:
        inputs.extend(["-i", str(f)])

    # Chain acrossfade filters
    n = len(mp3_files)
    filter_parts: list[str] = []
    # First crossfade: [0][1]
    filter_parts.append(
        f"[0:a][1:a]acrossfade=d={crossfade_dur}:c1=tri:c2=tri[a01]"
    )
    prev = "a01"
    for i in range(2, n):
        cur = f"a{prev}{i}"
        filter_parts.append(
            f"[{prev}][{i}:a]acrossfade=d={crossfade_dur}:c1=tri:c2=tri[{cur}]"
        )
        prev = cur

    filter_complex = ";".join(filter_parts)
    concat_out = output_path.with_suffix(".concat.mp3")

    ffmpeg.run([
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-c:a", "libmp3lame", "-b:a", cfg.audio_bitrate,
        str(concat_out),
    ], desc="Audio crossfade")

    _loop_and_trim(concat_out, video_duration, output_path, cfg)
    concat_out.unlink(missing_ok=True)


def _loop_and_trim(mp3_path: Path, video_duration: float, output_path: Path, cfg: Config) -> None:
    """Loop MP3 if shorter than video, trim to exact duration."""
    ffmpeg.run([
        "-stream_loop", "-1",
        "-i", str(mp3_path),
        "-t", str(video_duration),
        "-c:a", "libmp3lame", "-b:a", cfg.audio_bitrate,
        str(output_path),
    ], desc="Loop/trim audio")
