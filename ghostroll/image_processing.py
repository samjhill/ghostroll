from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


class ProcessingError(RuntimeError):
    pass


def render_jpeg_derivative(
    src_path: Path,
    *,
    dst_path: Path,
    max_long_edge: int,
    quality: int,
) -> None:
    """
    - Auto-orient using EXIF orientation
    - Resize to max long edge (only shrink)
    - Strip metadata (save without EXIF)
    """
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im)

            # Convert to RGB for consistent JPEG output
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            elif im.mode == "L":
                im = im.convert("RGB")

            w, h = im.size
            long_edge = max(w, h)
            if long_edge > max_long_edge:
                scale = max_long_edge / float(long_edge)
                new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
                im = im.resize(new_size, Image.Resampling.LANCZOS)

            im.save(
                dst_path,
                format="JPEG",
                quality=int(quality),
                optimize=True,
                progressive=True,
            )
    except Exception as e:  # noqa: BLE001 - we want a clean error surface
        raise ProcessingError(f"Failed processing {src_path} -> {dst_path}: {e}") from e


