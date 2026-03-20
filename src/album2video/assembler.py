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
from album2video.manifest import (
    Manifest, load_manifest, save_manifest, config_matches,
    find_new_files, make_source_entry, new_manifest,
    extract_image_metadata, extract_video_metadata,
)
from album2video import ffmpeg


def process_album(album: Album, cfg: Config) -> Path:
    """Full pipeline: clips -> concat -> mux audio -> __video.mp4"""
    output = album.path / "__video.mp4"
    manifest = load_manifest(album.path)

    # Check for config mismatch
    if manifest and not config_matches(manifest, cfg):
        print(f"\n  WARNING: Encoding config has changed since last run for '{album.name}'.")
        print("  A full re-encode is required. Proceeding with full re-encode.")
        manifest = None  # Force full re-encode

    # Incremental mode
    if manifest and output.exists():
        new_images, new_videos = find_new_files(
            manifest, album.images, album.videos,
        )
        if not new_images and not new_videos:
            # Check if audio changed
            current_audio = sorted(p.name for p in album.audio)
            if current_audio == sorted(manifest.audio):
                print(f"\n  '{album.name}': nothing to do (no new files)")
                return output
            else:
                # Audio changed — re-mux only
                return _remux_audio(album, cfg, output, manifest)

        return _incremental_append(
            album, cfg, output, manifest, new_images, new_videos,
        )

    # Full encode (first run or forced re-encode)
    return _full_encode(album, cfg, output)


def _full_encode(album: Album, cfg: Config, output: Path) -> Path:
    """Generate all clips and produce the video from scratch."""
    all_media = album.images + album.videos
    sorted_media = sort_media(all_media, cfg)

    print(f"\nProcessing '{album.name}': {len(album.images)} images, "
          f"{len(album.videos)} videos, {len(album.audio)} audio tracks")

    manifest = new_manifest(cfg)

    with tempfile.TemporaryDirectory(prefix="album2video_") as tmpdir:
        tmp = Path(tmpdir)
        clips: list[Path] = []
        durations: list[float] = []

        offset = 0.0
        for i, media in enumerate(sorted_media, 1):
            clip_path = tmp / f"clip_{i:04d}.mp4"
            ext = media.suffix.lower()
            tag = f"[{i}/{len(sorted_media)}]"
            try:
                if ext in IMAGE_EXTS:
                    print(f"  {tag} Image: {media.name}")
                    image_to_clip(media, clip_path, cfg, tmpdir=tmp)
                    dur = float(cfg.photo_duration)
                    media_type = "image"
                    metadata = extract_image_metadata(media)
                else:
                    print(f"  {tag} Video: {media.name}")
                    normalize_video(media, clip_path, cfg)
                    dur = ffmpeg.probe_duration(clip_path)
                    media_type = "video"
                    metadata = extract_video_metadata(media)
                clips.append(clip_path)
                durations.append(dur)
                manifest.sources.append(
                    make_source_entry(media, media_type, dur,
                                      metadata=metadata,
                                      video_offset_secs=offset)
                )
                offset += dur
            except Exception as e:
                print(f"  {tag} WARNING: skipping {media.name}: {e}",
                      file=sys.stderr)
                continue

        if not clips:
            raise RuntimeError(f"No clips generated for album '{album.name}'")

        _concat_and_mux(clips, album, cfg, output, tmp)

    manifest.audio = sorted(p.name for p in album.audio)
    save_manifest(album.path, manifest)
    print(f"\n  Output: {output}")
    return output


def _incremental_append(
    album: Album, cfg: Config, output: Path,
    manifest: Manifest, new_images: list[Path], new_videos: list[Path],
) -> Path:
    """Generate clips only for new files and append to existing video."""
    new_media = new_images + new_videos
    sorted_new = sort_media(new_media, cfg)

    print(f"\nIncremental update '{album.name}': {len(new_images)} new images, "
          f"{len(new_videos)} new videos")

    base_offset = ffmpeg.probe_duration(output)

    with tempfile.TemporaryDirectory(prefix="album2video_") as tmpdir:
        tmp = Path(tmpdir)
        clips: list[Path] = []
        new_entries: list[tuple[Path, str, float, dict, float]] = []
        offset = base_offset

        for i, media in enumerate(sorted_new, 1):
            clip_path = tmp / f"clip_{i:04d}.mp4"
            ext = media.suffix.lower()
            tag = f"[{i}/{len(sorted_new)}]"
            try:
                if ext in IMAGE_EXTS:
                    print(f"  {tag} Image: {media.name}")
                    image_to_clip(media, clip_path, cfg, tmpdir=tmp)
                    dur = float(cfg.photo_duration)
                    media_type = "image"
                    metadata = extract_image_metadata(media)
                else:
                    print(f"  {tag} Video: {media.name}")
                    normalize_video(media, clip_path, cfg)
                    dur = ffmpeg.probe_duration(clip_path)
                    media_type = "video"
                    metadata = extract_video_metadata(media)
                clips.append(clip_path)
                new_entries.append((media, media_type, dur, metadata, offset))
                offset += dur
            except Exception as e:
                print(f"  {tag} WARNING: skipping {media.name}: {e}",
                      file=sys.stderr)
                continue

        if not clips:
            print("  No new clips could be generated.")
            return output

        # Concat: existing video + new clips (stream copy)
        concat_list = tmp / "concat.txt"
        lines = [f"file '{output}'"]
        lines.extend(f"file '{c}'" for c in clips)
        concat_list.write_text("\n".join(lines))

        concat_video = tmp / "concat.mp4"
        ffmpeg.run([
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(concat_video),
        ], desc="Appending new clips to existing video")

        video_duration = ffmpeg.probe_duration(concat_video)
        print(f"  Total video duration: {video_duration:.1f}s")

        # Re-mux audio if present
        if album.audio:
            sorted_audio = sorted(album.audio, key=lambda p: p.name.lower())
            soundtrack = tmp / "soundtrack.mp3"
            build_soundtrack(sorted_audio, video_duration, soundtrack, cfg)

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
            ffmpeg.run([
                "-i", str(concat_video),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output),
            ], desc="Finalizing video")

    # Update manifest
    for media, media_type, dur, metadata, entry_offset in new_entries:
        manifest.sources.append(
            make_source_entry(media, media_type, dur,
                              metadata=metadata,
                              video_offset_secs=entry_offset)
        )
    manifest.audio = sorted(p.name for p in album.audio)
    save_manifest(album.path, manifest)

    print(f"\n  Output: {output}")
    return output


def _remux_audio(
    album: Album, cfg: Config, output: Path, manifest: Manifest,
) -> Path:
    """Re-mux existing video with new/changed audio tracks."""
    print(f"\n  '{album.name}': audio changed, re-muxing...")

    with tempfile.TemporaryDirectory(prefix="album2video_") as tmpdir:
        tmp = Path(tmpdir)
        video_duration = ffmpeg.probe_duration(output)

        # Copy existing video to temp to avoid reading and writing same file
        tmp_video = tmp / "existing.mp4"
        ffmpeg.run([
            "-i", str(output),
            "-c", "copy", "-an",
            str(tmp_video),
        ], desc="Extracting video stream")

        if album.audio:
            sorted_audio = sorted(album.audio, key=lambda p: p.name.lower())
            soundtrack = tmp / "soundtrack.mp3"
            build_soundtrack(sorted_audio, video_duration, soundtrack, cfg)

            ffmpeg.run([
                "-i", str(tmp_video),
                "-i", str(soundtrack),
                "-c:v", "copy",
                "-c:a", "libmp3lame", "-b:a", cfg.audio_bitrate,
                "-map", "0:v:0", "-map", "1:a:0",
                "-movflags", "+faststart",
                "-shortest",
                str(output),
            ], desc="Muxing video + new audio")
        else:
            ffmpeg.run([
                "-i", str(tmp_video),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output),
            ], desc="Removing audio from video")

    manifest.audio = sorted(p.name for p in album.audio)
    save_manifest(album.path, manifest)
    print(f"  Done re-muxing: {output}")
    return output


def cleanup_sources(album: Album) -> int:
    """Delete source media files listed in the manifest. Returns count deleted."""
    manifest = load_manifest(album.path)
    if not manifest:
        print(f"  No manifest found for '{album.name}', skipping cleanup.")
        return 0

    output = album.path / "__video.mp4"
    if not output.exists():
        print(f"  No video found for '{album.name}', skipping cleanup.")
        return 0

    deleted = 0
    for source in manifest.sources:
        src_path = album.path / source.path
        if src_path.exists():
            src_path.unlink()
            print(f"  Deleted: {source.path}")
            deleted += 1

    print(f"  Cleaned up {deleted} source files from '{album.name}'")
    return deleted


def _concat_and_mux(
    clips: list[Path], album: Album, cfg: Config,
    output: Path, tmp: Path,
) -> None:
    """Concat clips and mux with audio (shared by full encode)."""
    concat_list = tmp / "concat.txt"
    concat_list.write_text("\n".join(f"file '{c}'" for c in clips))
    concat_video = tmp / "concat.mp4"
    ffmpeg.run([
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(concat_video),
    ], desc="Concatenating clips")

    video_duration = ffmpeg.probe_duration(concat_video)
    print(f"  Total video duration: {video_duration:.1f}s")

    if album.audio:
        sorted_audio = sorted(album.audio, key=lambda p: p.name.lower())
        soundtrack = tmp / "soundtrack.mp3"
        build_soundtrack(sorted_audio, video_duration, soundtrack, cfg)

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
        ffmpeg.run([
            "-i", str(concat_video),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output),
        ], desc="Finalizing video")
