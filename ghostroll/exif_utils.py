from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class BasicExif:
    captured_at: datetime | None
    captured_at_display: str | None
    camera: str | None


def _parse_exif_datetime(s: str) -> datetime | None:
    """
    Common EXIF datetime format: 'YYYY:MM:DD HH:MM:SS'
    """
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y:%m:%d %H:%M:%S%z"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def extract_basic_exif(jpeg_path: Path) -> BasicExif:
    """
    Best-effort EXIF extraction for local UI only.
    Derived outputs strip EXIF, so call this on originals.
    """
    try:
        from PIL import Image
    except Exception:
        return BasicExif(captured_at=None, captured_at_display=None, camera=None)

    try:
        with Image.open(jpeg_path) as im:
            exif = im.getexif()
            if not exif:
                return BasicExif(captured_at=None, captured_at_display=None, camera=None)

            # EXIF tag IDs
            make = exif.get(271)
            model = exif.get(272)
            dt_original = exif.get(36867) or exif.get(306)  # DateTimeOriginal or DateTime

            captured_at = _parse_exif_datetime(str(dt_original) if dt_original is not None else "")
            captured_display = (
                captured_at.strftime("%Y-%m-%d %H:%M:%S") if captured_at is not None else None
            )

            make_s = str(make).strip() if make is not None else ""
            model_s = str(model).strip() if model is not None else ""
            camera = " ".join([p for p in [make_s, model_s] if p])
            if camera == "":
                camera = None

            return BasicExif(
                captured_at=captured_at,
                captured_at_display=captured_display,
                camera=camera,
            )
    except Exception:
        return BasicExif(captured_at=None, captured_at_display=None, camera=None)




