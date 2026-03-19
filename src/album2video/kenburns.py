from __future__ import annotations

import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

from album2video.config import Config

# Formats that ffmpeg can't read with -loop 1, need Pillow conversion
_NEEDS_CONVERSION = frozenset({
    ".heic", ".heif", ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf"
})

# Canvas is this many times the output resolution.
# Provides headroom for zoom/pan without showing canvas edges.
_CANVAS_SCALE = 2

# Portrait images fill this fraction of the output width
_IMAGE_FILL = 0.8

# Landscape zoom range (15%)
_ZOOM_AMOUNT = 0.15

# Portrait zoom range (25%, so zoom-out starts at >120%)
_ZOOM_AMOUNT_PORTRAIT = 0.25

# Pan drift: fraction of available margin for panning
_PAN_DRIFT = 0.3


def image_to_clip(image_path: Path, output_path: Path, cfg: Config,
                  tmpdir: Path | None = None) -> None:
    """Convert an image to a video clip (with or without Ken Burns)."""
    actual_input = _convert_to_jpeg(image_path, tmpdir)

    w, h = _get_dimensions(actual_input)
    is_portrait = h > w

    if cfg.ken_burns:
        _ken_burns_clip(actual_input, output_path, cfg, w, h, is_portrait,
                        image_path.name)
    else:
        _static_clip(actual_input, output_path, cfg, w, h, is_portrait,
                     image_path.name)


def _static_clip(input_path: Path, output_path: Path, cfg: Config,
                 w: int, h: int, is_portrait: bool, name: str) -> None:
    """Static image clip: portrait fits height, landscape fits width."""
    from album2video import ffmpeg
    ow, oh = cfg.output_width, cfg.output_height

    if is_portrait:
        fit_h = oh
        fit_w = int(w * fit_h / h)
    else:
        fit_w = ow
        fit_h = int(h * fit_w / w)

    fit_w += fit_w % 2
    fit_h += fit_h % 2

    vf = (
        f"scale={fit_w}:{fit_h},"
        f"pad={ow}:{oh}:({ow}-iw)/2:({oh}-ih)/2:black,"
        f"format=yuv420p"
    )
    ffmpeg.run([
        "-loop", "1", "-i", str(input_path),
        "-vf", vf,
        "-t", str(cfg.photo_duration),
        "-r", str(cfg.output_fps),
        "-c:v", "libx264",
        "-profile:v", cfg.h264_profile,
        "-level:v", cfg.h264_level,
        "-b:v", cfg.video_bitrate,
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ], desc=f"Static: {name}")


# ---------------------------------------------------------------------------
# Ken Burns via Pillow frame generation
# ---------------------------------------------------------------------------
# Instead of ffmpeg's zoompan (which truncates x/y to integers causing
# frame-to-frame jitter), we generate each frame with Pillow's
# Image.resize(box=...) which accepts float coordinates for sub-pixel
# precision. Frames are piped as raw RGB to ffmpeg for encoding.
# ---------------------------------------------------------------------------

def _build_canvas(input_path: Path, cfg: Config,
                  w: int, h: int, is_portrait: bool) -> Image.Image:
    """Compose image centered on a black canvas with zoom/pan headroom."""
    ow, oh = cfg.output_width, cfg.output_height
    canvas_w = ow * _CANVAS_SCALE
    canvas_h = oh * _CANVAS_SCALE

    fill = 1.0 if not is_portrait else _IMAGE_FILL
    fit_w = int(ow * fill)
    fit_h = int(h * fit_w / w)

    if is_portrait:
        max_h = int(oh * 0.9)
        if fit_h > max_h:
            fit_h = max_h
            fit_w = int(w * fit_h / h)

    with Image.open(input_path) as img:
        resized = img.resize((fit_w, fit_h), Image.LANCZOS)

    canvas = Image.new("RGB", (canvas_w, canvas_h), (0, 0, 0))
    paste_x = (canvas_w - fit_w) // 2
    paste_y = (canvas_h - fit_h) // 2
    canvas.paste(resized, (paste_x, paste_y))
    return canvas


def _make_box(cx: float, cy: float,
              crop_w: float, crop_h: float) -> tuple[float, float, float, float]:
    return (cx - crop_w / 2, cy - crop_h / 2,
            cx + crop_w / 2, cy + crop_h / 2)


def _lerp_box(start: tuple[float, ...], end: tuple[float, ...],
              t: float) -> tuple[float, ...]:
    return tuple(s + (e - s) * t for s, e in zip(start, end))


def _ken_burns_clip(input_path: Path, output_path: Path, cfg: Config,
                    w: int, h: int, is_portrait: bool, name: str) -> None:
    """Ken Burns clip: Pillow generates frames, piped to ffmpeg for encoding."""
    ow, oh = cfg.output_width, cfg.output_height
    total_frames = cfg.photo_duration * cfg.output_fps

    canvas = _build_canvas(input_path, cfg, w, h, is_portrait)
    canvas_w, canvas_h = canvas.size
    cx, cy = canvas_w / 2.0, canvas_h / 2.0

    preset = random.choice(_PRESETS_PORTRAIT if is_portrait else _PRESETS_LANDSCAPE)
    start_box, end_box = preset(canvas_w, canvas_h, ow, oh, cx, cy)

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{ow}x{oh}", "-r", str(cfg.output_fps),
        "-i", "pipe:0",
        "-vframes", str(total_frames),
        "-c:v", "libx264",
        "-profile:v", cfg.h264_profile,
        "-level:v", cfg.h264_level,
        "-b:v", cfg.video_bitrate,
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ]

    print(f"  [kenburns] {name}: generating {total_frames} frames")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    try:
        for i in range(total_frames):
            t = i / max(total_frames - 1, 1)
            box = _lerp_box(start_box, end_box, t)
            frame = canvas.resize((ow, oh), Image.LANCZOS, box=box)
            proc.stdin.write(frame.tobytes())
        proc.stdin.flush()
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass

    proc.wait()
    if proc.returncode != 0:
        stderr_text = proc.stderr.read().decode(errors="replace")[-2000:]
        print(f"  [kenburns] FAILED:\n{stderr_text}", file=sys.stderr)
        raise RuntimeError(f"ffmpeg encode failed for {name}")


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------
# Each returns (start_box, end_box) as float 4-tuples (left, top, right, bottom)
# in canvas pixel coordinates. Frames linearly interpolate between them.
#
# "zoom in" = crop shrinks over time (seeing less → magnified more)
# "zoom out" = crop grows over time (seeing more → magnified less)
# At zoom_factor z: crop size = (ow/z, oh/z)
#   z = 1.0 → crop equals output size (normal view of canvas)
#   z = 1.15 → 15% zoom in (crop is smaller, resized up to output)

# --- Landscape presets ---

def _l_zoom_in_pan_right(cw, ch, ow, oh, cx, cy):
    start = _make_box(cx, cy, ow, oh)
    end_cw, end_ch = ow / (1 + _ZOOM_AMOUNT), oh / (1 + _ZOOM_AMOUNT)
    margin_x = (cw - end_cw) / 2
    end = _make_box(cx + margin_x * _PAN_DRIFT, cy, end_cw, end_ch)
    return start, end

def _l_zoom_in_pan_left(cw, ch, ow, oh, cx, cy):
    start = _make_box(cx, cy, ow, oh)
    end_cw, end_ch = ow / (1 + _ZOOM_AMOUNT), oh / (1 + _ZOOM_AMOUNT)
    margin_x = (cw - end_cw) / 2
    end = _make_box(cx - margin_x * _PAN_DRIFT, cy, end_cw, end_ch)
    return start, end

def _l_zoom_out_center(cw, ch, ow, oh, cx, cy):
    z = 1 + _ZOOM_AMOUNT
    start = _make_box(cx, cy, ow / z, oh / z)
    end = _make_box(cx, cy, ow, oh)
    return start, end

def _l_zoom_in_center(cw, ch, ow, oh, cx, cy):
    z = 1 + _ZOOM_AMOUNT
    start = _make_box(cx, cy, ow, oh)
    end = _make_box(cx, cy, ow / z, oh / z)
    return start, end

def _l_zoom_in_pan_down(cw, ch, ow, oh, cx, cy):
    start = _make_box(cx, cy, ow, oh)
    end_cw, end_ch = ow / (1 + _ZOOM_AMOUNT), oh / (1 + _ZOOM_AMOUNT)
    margin_y = (ch - end_ch) / 2
    end = _make_box(cx, cy + margin_y * _PAN_DRIFT, end_cw, end_ch)
    return start, end

def _l_zoom_out_pan_up(cw, ch, ow, oh, cx, cy):
    z = 1 + _ZOOM_AMOUNT
    start_cw, start_ch = ow / z, oh / z
    margin_y = (ch - start_cw) / 2
    start = _make_box(cx, cy + margin_y * _PAN_DRIFT * 0.5, start_cw, start_ch)
    end = _make_box(cx, cy - margin_y * _PAN_DRIFT * 0.5, ow, oh)
    return start, end


# --- Portrait presets: zoom only, no pan ---

def _p_zoom_in(cw, ch, ow, oh, cx, cy):
    z = 1 + _ZOOM_AMOUNT_PORTRAIT
    start = _make_box(cx, cy, ow, oh)
    end = _make_box(cx, cy, ow / z, oh / z)
    return start, end

def _p_zoom_out(cw, ch, ow, oh, cx, cy):
    z = 1 + _ZOOM_AMOUNT_PORTRAIT
    start = _make_box(cx, cy, ow / z, oh / z)
    end = _make_box(cx, cy, ow, oh)
    return start, end


_PRESETS_LANDSCAPE = [
    _l_zoom_in_pan_right,
    _l_zoom_in_pan_left,
    _l_zoom_out_center,
    _l_zoom_in_center,
    _l_zoom_in_pan_down,
    _l_zoom_out_pan_up,
]

_PRESETS_PORTRAIT = [
    _p_zoom_in,
    _p_zoom_out,
]


# ---------------------------------------------------------------------------
# Image conversion helpers
# ---------------------------------------------------------------------------

def _convert_to_jpeg(image_path: Path, tmpdir: Path | None = None) -> Path:
    """Convert any image to orientation-corrected JPEG via Pillow."""
    ext = image_path.suffix.lower()
    if ext in {".heic", ".heif"}:
        import pillow_heif
        pillow_heif.register_heif_opener()

    out_dir = tmpdir or Path(tempfile.gettempdir())
    out_path = out_dir / f"{image_path.stem}_converted.jpg"
    with Image.open(image_path) as img:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        img.convert("RGB").save(out_path, "JPEG", quality=95)
    return out_path


def _get_dimensions(path: Path) -> tuple[int, int]:
    """Get image dimensions, accounting for EXIF orientation."""
    from PIL import ImageOps
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        return img.size
