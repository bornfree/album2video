from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from album2video.config import Config, IMAGE_EXTS
from album2video.scanner import Album
from album2video.sorter import sort_media
from album2video.kenburns import image_to_clip
from album2video.video_proc import normalize_video
from album2video.audio import build_soundtrack
from album2video import ffmpeg


def process_album(album: Album, cfg: Config) -> Path:
    """Full pipeline: clips → concat → mux audio → __video.mp4"""
    output = album.path / "__video.mp4"
    all_media = album.images + album.videos
    sorted_media = sort_media(all_media, cfg)

    print(f"\nProcessing '{album.name}': {len(album.images)} images, "
          f"{len(album.videos)} videos, {len(album.audio)} audio tracks")

    with tempfile.TemporaryDirectory(prefix="album2video_") as tmpdir:
        tmp = Path(tmpdir)
        clips: list[Path] = []

        # Generate clips
        for i, media in enumerate(sorted_media, 1):
            clip_path = tmp / f"clip_{i:04d}.mp4"
            ext = media.suffix.lower()
            tag = f"[{i}/{len(sorted_media)}]"
            try:
                if ext in IMAGE_EXTS:
                    print(f"  {tag} Image: {media.name}")
                    image_to_clip(media, clip_path, cfg, tmpdir=tmp)
                else:
                    print(f"  {tag} Video: {media.name}")
                    normalize_video(media, clip_path, cfg)
                clips.append(clip_path)
            except Exception as e:
                print(f"  {tag} WARNING: skipping {media.name}: {e}", file=sys.stderr)
                continue

        if not clips:
            raise RuntimeError(f"No clips generated for album '{album.name}'")

        # Concat clips via demuxer (stream copy - fast)
        concat_list = tmp / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{c}'" for c in clips)
        )
        concat_video = tmp / "concat.mp4"
        ffmpeg.run([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(concat_video),
        ], desc="Concatenating clips")

        video_duration = ffmpeg.probe_duration(concat_video)
        print(f"  Total video duration: {video_duration:.1f}s")

        # Audio
        if album.audio:
            sorted_audio = sorted(album.audio, key=lambda p: p.name.lower())
            soundtrack = tmp / "soundtrack.mp3"
            build_soundtrack(sorted_audio, video_duration, soundtrack, cfg)

            # Mux video + audio
            ffmpeg.run([
                "-i", str(concat_video),
                "-i", str(soundtrack),
                "-c:v", "copy",
                "-c:a", "libmp3lame", "-b:a", cfg.audio_bitrate,
                "-map", "0:v:0", "-map", "1:a:0",
                "-movflags", "+faststart",
                "-shortest",
                str(output),
            ], desc="Muxing video + audio")
        else:
            # No audio - just add faststart
            ffmpeg.run([
                "-i", str(concat_video),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output),
            ], desc="Finalizing video")

    print(f"\n  Output: {output}")
    return output
