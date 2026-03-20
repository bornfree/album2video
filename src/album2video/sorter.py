from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from pathlib import Path

from album2video.config import IMAGE_EXTS, Config
from album2video.ffmpeg import probe_creation_time


def sort_media(files: list[Path], cfg: Config) -> list[Path]:
    if cfg.sort_order == "random":
        out = list(files)
        random.shuffle(out)
        return out
    if cfg.sort_order == "name":
        return sorted(files, key=_natural_key)
    # date sort
    dated: list[tuple[datetime | None, Path]] = []
    for f in files:
        dated.append((_extract_date(f), f))
    # stable sort: files with dates first (sorted by date), then files without dates (sorted by name)
    with_date = [(d, p) for d, p in dated if d is not None]
    without_date = [p for d, p in dated if d is None]
    # Normalize: convert aware datetimes (UTC from ffprobe) to local time,
    # then compare as naive — EXIF dates are already naive local time
    with_date.sort(key=lambda x: x[0].astimezone().replace(tzinfo=None) if x[0].tzinfo else x[0])
    without_date.sort(key=_natural_key)
    return [p for _, p in with_date] + without_date


def _natural_key(path: Path) -> list:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def _extract_date(path: Path) -> datetime | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return _exif_date(path)
    return _video_date(path)


def _exif_date(path: Path) -> datetime | None:
    try:
        from PIL import Image
        from PIL.ExifTags import Base as ExifBase
        import pillow_heif
        pillow_heif.register_heif_opener()
        with Image.open(path) as img:
            exif = img.getexif()
            raw = exif.get(ExifBase.DateTimeOriginal) or exif.get(ExifBase.DateTime)
            if raw:
                return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def _video_date(path: Path) -> datetime | None:
    try:
        ct = probe_creation_time(path)
        if ct:
            # ISO 8601 format from ffprobe
            return datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except Exception:
        pass
    return None
