# album2video

Converts travel photo/video albums into 4K H.264 MP4 files for Raspberry Pi playback.

## Quick Reference

```bash
uv sync              # install dependencies
uv run album2video   # run the CLI
```

## Project Layout

```
src/album2video/
  cli.py         # Interactive CLI entry point
  config.py      # Config dataclass, .env loading, file extension constants
  scanner.py     # Album/media discovery under ALBUM_ROOT
  sorter.py      # Sort media by EXIF date, name, or random
  assembler.py   # Pipeline orchestrator: full encode, incremental append, audio remux
  manifest.py    # JSON manifest tracking (SHA256 hashes, metadata)
  kenburns.py    # Ken Burns zoom/pan animation (Pillow frame generation)
  video_proc.py  # Video normalization (scale/pad to output resolution)
  audio.py       # Audio crossfading, looping, trimming
  ffmpeg.py      # ffmpeg/ffprobe subprocess wrapper
```

## Configuration

All settings via `.env` (see `.env.example`). `ALBUM_ROOT` is required.

## External Dependencies

Requires `ffmpeg` and `ffprobe` on PATH.

## Package Manager

Use `uv` for all dependency and environment management. Do not use pip directly.

## Key Patterns

- **Incremental processing**: SHA256 manifest tracks processed files; only new files are encoded.
- **Ken Burns**: Pillow generates frames at 2x resolution for sub-pixel smooth zoom/pan, piped to ffmpeg.
- **Stream copy**: Concatenation uses `-c copy` to avoid re-encoding.
- **Config change detection**: Manifest stores config snapshot; mismatch triggers full re-encode.
- Output files: `__video.mp4` and `__video.manifest.json` in each album folder.
