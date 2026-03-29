from __future__ import annotations

import random
import re
from datetime import datetime, timezone, timedelta
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
    # date sort — all datetimes normalized to UTC for consistent ordering
    dated: list[tuple[datetime | None, Path]] = []
    for f in files:
        dated.append((_extract_date(f), f))
    with_date = [(d, p) for d, p in dated if d is not None]
    without_date = [p for d, p in dated if d is None]
    with_date.sort(key=lambda x: x[0])
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
            ifd = exif.get_ifd(0x8769)  # EXIF sub-IFD
            raw = (
                ifd.get(36867)  # DateTimeOriginal
                or ifd.get(36868)  # DateTimeDigitized
                or exif.get(ExifBase.DateTimeOriginal)
                or exif.get(ExifBase.DateTime)
            )
            if not raw:
                return None
            dt = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
            # OffsetTimeOriginal (tag 36881) in EXIF sub-IFD, e.g. "+05:30"
            offset_str = ifd.get(36881)
            if offset_str:
                tz = _parse_offset(offset_str)
                if tz is not None:
                    return dt.replace(tzinfo=tz).astimezone(timezone.utc)
            # No offset available — assume UTC for consistent sorting
            return dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    return None


def _video_date(path: Path) -> datetime | None:
    try:
        ct = probe_creation_time(path)
        if ct:
            # ffprobe creation_time is UTC (ISO 8601 with Z or +00:00)
            return datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except Exception:
        pass
    return None


def _parse_offset(offset_str: str) -> timezone | None:
    """Parse an offset string like '+05:30' or '+0530' into a timezone."""
    try:
        offset_str = offset_str.strip()
        sign = 1 if offset_str[0] == "+" else -1
        digits = offset_str[1:].replace(":", "")
        hours = int(digits[:2])
        minutes = int(digits[2:4]) if len(digits) >= 4 else 0
        return timezone(timedelta(hours=sign * hours, minutes=sign * minutes))
    except Exception:
        return None
