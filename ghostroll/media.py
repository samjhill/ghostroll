from __future__ import annotations

from pathlib import Path


JPEG_EXTS = {".jpg", ".jpeg"}
RAW_EXTS = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2"}


def is_jpeg(path: Path) -> bool:
    return path.suffix.lower() in JPEG_EXTS


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTS


def is_media(path: Path) -> bool:
    s = path.suffix.lower()
    return s in JPEG_EXTS or s in RAW_EXTS




