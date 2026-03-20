from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from album2video.config import Config

MANIFEST_NAME = "__video.manifest.json"


@dataclass
class ManifestSource:
    path: str
    type: str  # "image" or "video"
    sha256: str
    duration_secs: float
    added_at: str

    # Video timeline position
    video_offset_secs: float | None = None

    # Creation timestamp
    created_at_local: str | None = None
    timezone_offset: str | None = None

    # Device
    device_make: str | None = None
    device_model: str | None = None

    # GPS
    gps_location: str | None = None

    # Dimensions
    width: int | None = None
    height: int | None = None

    # Camera settings (images)
    focal_length_mm: float | None = None
    focal_length_35mm: int | None = None
    f_number: float | None = None
    iso: int | None = None
    exposure_time: float | None = None

    # Video-specific
    original_codec: str | None = None
    original_fps: float | None = None


@dataclass
class Manifest:
    version: int = 1
    created_at: str = ""
    updated_at: str = ""
    config: dict = field(default_factory=dict)
    sources: list[ManifestSource] = field(default_factory=list)
    audio: list[str] = field(default_factory=list)
    output: str = "__video.mp4"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_dict(cfg: Config) -> dict:
    return {
        "output_width": cfg.output_width,
        "output_height": cfg.output_height,
        "output_fps": cfg.output_fps,
        "video_bitrate": cfg.video_bitrate,
        "ken_burns": cfg.ken_burns,
        "photo_duration": cfg.photo_duration,
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rational_to_float(val) -> float | None:
    """Convert a PIL IFDRational or tuple to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _parse_gps_coord(coord_tuple, ref: str) -> float | None:
    """Convert GPS DMS tuple ((deg, min, sec), ref) to decimal degrees."""
    if not coord_tuple or len(coord_tuple) < 3:
        return None
    try:
        degrees = float(coord_tuple[0])
        minutes = float(coord_tuple[1])
        seconds = float(coord_tuple[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _format_iso6709(lat: float, lon: float, alt: float | None = None) -> str:
    """Format lat/lon/alt as ISO 6709 string."""
    lat_sign = "+" if lat >= 0 else ""
    lon_sign = "+" if lon >= 0 else ""
    s = f"{lat_sign}{lat:.4f}{lon_sign}{lon:.4f}"
    if alt is not None:
        alt_sign = "+" if alt >= 0 else ""
        s += f"{alt_sign}{alt:.3f}"
    return s + "/"


def extract_image_metadata(path: Path) -> dict:
    """Extract EXIF metadata from an image file."""
    meta: dict = {}
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    try:
        from PIL import Image
        from PIL.ExifTags import Base as ExifBase, GPS as GPSTags
    except ImportError:
        return meta

    try:
        img = Image.open(path)
    except Exception:
        return meta

    # Get dimensions (after orientation)
    meta["width"] = img.width
    meta["height"] = img.height

    exif = img.getexif()
    if not exif:
        return meta

    # Basic EXIF tags
    if val := exif.get(ExifBase.DateTimeOriginal):
        meta["created_at_local"] = str(val)
    if val := exif.get(ExifBase.OffsetTimeOriginal):
        meta["timezone_offset"] = str(val)
    if val := exif.get(ExifBase.Make):
        meta["device_make"] = str(val).strip()
    if val := exif.get(ExifBase.Model):
        meta["device_model"] = str(val).strip()

    # IFD EXIF block (camera settings live here)
    ifd_exif = exif.get_ifd(ExifBase.ExifOffset)

    if ifd_exif:
        # Override date/tz from IFD if not found in root
        if "created_at_local" not in meta:
            if val := ifd_exif.get(ExifBase.DateTimeOriginal):
                meta["created_at_local"] = str(val)
        if "timezone_offset" not in meta:
            if val := ifd_exif.get(ExifBase.OffsetTimeOriginal):
                meta["timezone_offset"] = str(val)

        if (val := _rational_to_float(ifd_exif.get(ExifBase.FocalLength))) is not None:
            meta["focal_length_mm"] = round(val, 2)
        if val := ifd_exif.get(ExifBase.FocalLengthIn35mmFilm):
            meta["focal_length_35mm"] = int(val)
        if (val := _rational_to_float(ifd_exif.get(ExifBase.FNumber))) is not None:
            meta["f_number"] = round(val, 1)
        if val := ifd_exif.get(ExifBase.ISOSpeedRatings):
            meta["iso"] = int(val)
        if (val := _rational_to_float(ifd_exif.get(ExifBase.ExposureTime))) is not None:
            meta["exposure_time"] = val

    # GPS
    gps_ifd = exif.get_ifd(ExifBase.GPSInfo)
    if gps_ifd:
        lat = _parse_gps_coord(
            gps_ifd.get(GPSTags.GPSLatitude),
            gps_ifd.get(GPSTags.GPSLatitudeRef, "N"),
        )
        lon = _parse_gps_coord(
            gps_ifd.get(GPSTags.GPSLongitude),
            gps_ifd.get(GPSTags.GPSLongitudeRef, "E"),
        )
        alt = None
        if alt_val := gps_ifd.get(GPSTags.GPSAltitude):
            try:
                alt = float(alt_val)
                if gps_ifd.get(GPSTags.GPSAltitudeRef, 0) == 1:
                    alt = -alt
            except (TypeError, ValueError):
                pass
        if lat is not None and lon is not None:
            meta["gps_location"] = _format_iso6709(lat, lon, alt)

    return meta


def extract_video_metadata(path: Path) -> dict:
    """Extract metadata from a video file using ffprobe."""
    meta: dict = {}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
    except Exception:
        return meta

    fmt = data.get("format", {})
    fmt_tags = fmt.get("tags", {})

    # Device info — prefer Apple QuickTime tags
    meta["device_make"] = (
        fmt_tags.get("com.apple.quicktime.make")
        or fmt_tags.get("make")
        or None
    )
    meta["device_model"] = (
        fmt_tags.get("com.apple.quicktime.model")
        or fmt_tags.get("model")
        or None
    )

    # Creation time — prefer Apple local timestamp with offset
    apple_date = fmt_tags.get("com.apple.quicktime.creationdate")
    if apple_date:
        # e.g. "2026-03-07T22:27:02+0700"
        # Split into local datetime and offset
        if len(apple_date) >= 19:
            meta["created_at_local"] = apple_date[:19].replace("T", " ")
            if len(apple_date) > 19:
                tz_part = apple_date[19:]
                # Normalize "+0700" → "+07:00"
                if len(tz_part) == 5 and ":" not in tz_part:
                    tz_part = tz_part[:3] + ":" + tz_part[3:]
                meta["timezone_offset"] = tz_part
    elif creation_time := fmt_tags.get("creation_time"):
        meta["created_at_local"] = creation_time[:19].replace("T", " ")

    # GPS
    gps_iso = fmt_tags.get("com.apple.quicktime.location.ISO6709")
    if gps_iso:
        meta["gps_location"] = gps_iso

    # Video stream info
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            if w := stream.get("width"):
                meta["width"] = int(w)
            if h := stream.get("height"):
                meta["height"] = int(h)
            if codec := stream.get("codec_name"):
                meta["original_codec"] = codec
            if fps_str := stream.get("r_frame_rate"):
                try:
                    num, den = fps_str.split("/")
                    meta["original_fps"] = round(int(num) / int(den), 2)
                except (ValueError, ZeroDivisionError):
                    pass
            break

    # Strip None values
    return {k: v for k, v in meta.items() if v is not None}


def load_manifest(album_path: Path) -> Manifest | None:
    mpath = album_path / MANIFEST_NAME
    if not mpath.exists():
        return None
    data = json.loads(mpath.read_text())
    sources = []
    for s in data.get("sources", []):
        # Filter to only fields ManifestSource accepts (forward compat)
        valid_fields = {f.name for f in ManifestSource.__dataclass_fields__.values()}
        filtered = {k: v for k, v in s.items() if k in valid_fields}
        sources.append(ManifestSource(**filtered))
    return Manifest(
        version=data.get("version", 1),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        config=data.get("config", {}),
        sources=sources,
        audio=data.get("audio", []),
        output=data.get("output", "__video.mp4"),
    )


def save_manifest(album_path: Path, manifest: Manifest) -> None:
    manifest.updated_at = _now_iso()
    if not manifest.created_at:
        manifest.created_at = manifest.updated_at
    data = asdict(manifest)
    mpath = album_path / MANIFEST_NAME
    mpath.write_text(json.dumps(data, indent=2) + "\n")


def config_matches(manifest: Manifest, cfg: Config) -> bool:
    return manifest.config == _config_dict(cfg)


def find_new_files(
    manifest: Manifest,
    current_images: list[Path],
    current_videos: list[Path],
) -> tuple[list[Path], list[Path]]:
    known_hashes = {s.sha256 for s in manifest.sources}
    new_images: list[Path] = []
    new_videos: list[Path] = []

    for img in current_images:
        if _sha256(img) not in known_hashes:
            new_images.append(img)

    for vid in current_videos:
        if _sha256(vid) not in known_hashes:
            new_videos.append(vid)

    return new_images, new_videos


def make_source_entry(
    path: Path, media_type: str, duration_secs: float,
    metadata: dict | None = None,
    video_offset_secs: float | None = None,
) -> ManifestSource:
    entry = ManifestSource(
        path=path.name,
        type=media_type,
        sha256=_sha256(path),
        duration_secs=duration_secs,
        added_at=_now_iso(),
        video_offset_secs=video_offset_secs,
    )
    if metadata:
        for key, value in metadata.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
    return entry


def new_manifest(cfg: Config) -> Manifest:
    return Manifest(
        config=_config_dict(cfg),
        created_at=_now_iso(),
    )
