# album2video

Convert travel photo and video albums into 4K MP4 files optimized for Raspberry Pi playback.

album2video takes a folder of albums — each containing photos, videos, and optional MP3 audio — and produces a single H.264 4K video per album with Ken Burns zoom/pan effects on photos, normalized video segments, and a crossfaded audio soundtrack.

## Features

- **Incremental processing** — only encodes new files; appends to existing videos via SHA256 manifest tracking
- **Ken Burns effect** — smooth zoom/pan animations on photos with 8 presets (6 landscape, 2 portrait)
- **Wide format support** — JPEG, HEIC, TIFF, RAW (ARW, CR2, CR3, NEF, DNG, RAF), PNG for images; MP4, MOV, MKV, AVI for videos; MP3 for audio
- **Audio crossfading** — seamlessly blends multiple MP3 tracks with configurable fade duration
- **Metadata preservation** — extracts EXIF/GPS data and stores it in a JSON manifest
- **4K H.264 output** — configurable resolution, bitrate, profile, and level
- **Optional source cleanup** — delete originals after successful encoding

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- `ffmpeg` and `ffprobe` installed and available on PATH

## Installation

```bash
git clone https://github.com/your-username/album2video.git
cd album2video
uv sync
```

## Configuration

Copy the example environment file and edit it:

```bash
cp .env.example .env
```

Set `ALBUM_ROOT` to the path containing your album folders:

```
ALBUM_ROOT=/path/to/albums
```

### All Settings

| Variable | Default | Description |
|---|---|---|
| `ALBUM_ROOT` | *required* | Path to folder containing album subfolders |
| `OUTPUT_WIDTH` | `3840` | Output video width in pixels |
| `OUTPUT_HEIGHT` | `2160` | Output video height in pixels |
| `OUTPUT_FPS` | `30` | Frame rate |
| `VIDEO_BITRATE` | `20M` | H.264 bitrate |
| `H264_PROFILE` | `high` | H.264 profile |
| `H264_LEVEL` | `5.1` | H.264 level |
| `AUDIO_BITRATE` | `192k` | Audio bitrate |
| `SORT_ORDER` | `date` | Sort media by `date` (EXIF), `name`, or `random` |
| `PHOTO_DURATION` | `10` | Seconds to display each photo |
| `AUDIO_CROSSFADE` | `3` | Crossfade duration between MP3 tracks (seconds) |
| `KEN_BURNS` | `true` | Enable zoom/pan effect on photos |
| `CLEANUP_SOURCES` | `false` | Delete source files after encoding |

## Usage

```bash
uv run album2video
```

The interactive CLI will:

1. Scan `ALBUM_ROOT` for album folders
2. Display each album with media counts and completion status
3. Prompt you to select an album (by number), process all (`a`), or quit (`q`)

### Album Folder Structure

```
ALBUM_ROOT/
├── vacation-2024/
│   ├── IMG_0001.jpg
│   ├── IMG_0002.heic
│   ├── VID_0003.mp4
│   └── soundtrack.mp3
├── birthday-party/
│   ├── photo1.arw
│   ├── photo2.cr3
│   └── music.mp3
```

Each album produces `__video.mp4` and `__video.manifest.json` in its folder.

### Cleanup Mode

To delete source files after successful encoding:

```bash
uv run album2video --cleanup-sources
```

Or set `CLEANUP_SOURCES=true` in `.env`.

## How It Works

1. **Scan** — discovers images, videos, and audio in each album folder
2. **Sort** — orders media by EXIF date, filename, or randomly
3. **Encode** — images get Ken Burns animation (Pillow → ffmpeg); videos are normalized to output resolution
4. **Concatenate** — clips are joined via stream copy (no re-encoding)
5. **Mux audio** — MP3 tracks are crossfaded, looped to video length, and muxed in
6. **Manifest** — SHA256 hashes and metadata are saved for incremental processing

On subsequent runs, only new files are processed and appended to the existing video.

## License

MIT
