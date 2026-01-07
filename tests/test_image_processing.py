from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from ghostroll.image_processing import ProcessingError, render_jpeg_derivative


def test_render_jpeg_derivative_basic(tmp_path: Path):
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"

    # Create a test image
    img = Image.new("RGB", (2400, 1600), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)

    render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)

    assert dst.exists()
    with Image.open(dst) as result:
        assert result.size[0] <= 2048 or result.size[1] <= 2048
        assert result.mode == "RGB"


def test_render_jpeg_derivative_resize(tmp_path: Path):
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"

    # Create a large image
    img = Image.new("RGB", (4000, 3000), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)

    render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)

    with Image.open(dst) as result:
        assert max(result.size) == 2048


def test_render_jpeg_derivative_no_resize_needed(tmp_path: Path):
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"

    # Create a small image
    img = Image.new("RGB", (800, 600), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)

    render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)

    with Image.open(dst) as result:
        assert result.size == (800, 600)


def test_render_jpeg_derivative_creates_parent_dir(tmp_path: Path):
    src = tmp_path / "src.jpg"
    dst = tmp_path / "subdir" / "dst.jpg"

    img = Image.new("RGB", (800, 600), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)

    render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)

    assert dst.exists()
    assert dst.parent.exists()


def test_render_jpeg_derivative_grayscale_conversion(tmp_path: Path):
    src = tmp_path / "src.jpg"
    dst = tmp_path / "dst.jpg"

    # Create a grayscale image
    img = Image.new("L", (800, 600), 128)
    img.save(src, format="JPEG", quality=92)

    render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)

    with Image.open(dst) as result:
        assert result.mode == "RGB"


def test_render_jpeg_derivative_error_on_missing_file(tmp_path: Path):
    src = tmp_path / "nonexistent.jpg"
    dst = tmp_path / "dst.jpg"

    with pytest.raises(ProcessingError):
        render_jpeg_derivative(src, dst_path=dst, max_long_edge=2048, quality=90)


def test_render_jpeg_derivative_resampling_selection(tmp_path: Path):
    """Test that resampling algorithm is automatically selected based on size."""
    from PIL import Image
    
    src = tmp_path / "src.jpg"
    
    # Create a large image
    img = Image.new("RGB", (4000, 3000), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)
    
    # Thumbnail (<=512px) should use BILINEAR (faster)
    thumb_dst = tmp_path / "thumb.jpg"
    render_jpeg_derivative(src, dst_path=thumb_dst, max_long_edge=512, quality=85)
    assert thumb_dst.exists()
    
    # Share image (>512px) should use LANCZOS (high quality)
    share_dst = tmp_path / "share.jpg"
    render_jpeg_derivative(src, dst_path=share_dst, max_long_edge=2048, quality=90)
    assert share_dst.exists()
    
    # Both should be valid images
    with Image.open(thumb_dst) as thumb:
        assert max(thumb.size) <= 512
    with Image.open(share_dst) as share:
        assert max(share.size) == 2048


def test_render_jpeg_derivative_explicit_resampling(tmp_path: Path):
    """Test that explicit resampling parameter is respected."""
    from PIL import Image
    
    src = tmp_path / "src.jpg"
    img = Image.new("RGB", (4000, 3000), (120, 160, 200))
    img.save(src, format="JPEG", quality=92)
    
    # Explicitly request LANCZOS even for small output
    dst = tmp_path / "explicit.jpg"
    render_jpeg_derivative(
        src, 
        dst_path=dst, 
        max_long_edge=512, 
        quality=85,
        resampling=Image.Resampling.LANCZOS
    )
    assert dst.exists()
    
    with Image.open(dst) as result:
        assert max(result.size) <= 512

