from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run(args: list[str], desc: str = "") -> subprocess.CompletedProcess[str]:
    cmd = ["ffmpeg", "-hide_banner", "-y", *args]
    if desc:
        print(f"  [ffmpeg] {desc}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ffmpeg] FAILED: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr, file=sys.stderr)
        raise RuntimeError(f"ffmpeg failed: {desc}")
    return result


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def probe_creation_time(path: Path) -> str | None:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_entries", "format_tags=creation_time", str(path)],
        capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    tags = data.get("format", {}).get("tags", {})
    return tags.get("creation_time")
