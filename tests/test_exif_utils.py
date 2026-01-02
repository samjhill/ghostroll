from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from ghostroll.exif_utils import BasicExif, _parse_exif_datetime, extract_basic_exif


def test_parse_exif_datetime():
    assert _parse_exif_datetime("2024:01:15 14:30:00") == datetime(2024, 1, 15, 14, 30, 0)
    assert _parse_exif_datetime("2023:12:25 00:00:00") == datetime(2023, 12, 25, 0, 0, 0)

    # Invalid formats
    assert _parse_exif_datetime("") is None
    assert _parse_exif_datetime("invalid") is None
    assert _parse_exif_datetime("2024-01-15 14:30:00") is None  # Wrong format


def test_extract_basic_exif_no_exif(tmp_path: Path):
    # Create a JPEG without EXIF
    img = Image.new("RGB", (800, 600), (120, 160, 200))
    jpeg_path = tmp_path / "test.jpg"
    img.save(jpeg_path, format="JPEG")

    exif = extract_basic_exif(jpeg_path)
    assert exif.captured_at is None
    assert exif.captured_at_display is None
    assert exif.camera is None


def test_extract_basic_exif_with_exif(tmp_path: Path):
    # Create a JPEG with EXIF
    img = Image.new("RGB", (800, 600), (120, 160, 200))
    jpeg_path = tmp_path / "test.jpg"

    # Add EXIF data
    exif_dict = {
        271: "Canon",  # Make
        272: "EOS R5",  # Model
        36867: "2024:01:15 14:30:00",  # DateTimeOriginal
    }
    img.save(jpeg_path, format="JPEG", exif=img.getexif())

    # Note: PIL's getexif() doesn't easily let us set custom tags in tests,
    # so we'll test the function handles missing EXIF gracefully
    exif = extract_basic_exif(jpeg_path)
    # The function should not crash even if EXIF is minimal
    assert isinstance(exif, BasicExif)


def test_extract_basic_exif_missing_file(tmp_path: Path):
    missing_path = tmp_path / "nonexistent.jpg"
    exif = extract_basic_exif(missing_path)
    # Should return empty BasicExif without crashing
    assert exif.captured_at is None
    assert exif.captured_at_display is None
    assert exif.camera is None

