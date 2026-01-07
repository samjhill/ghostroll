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
    resampling: Image.Resampling | None = None,
) -> None:
    """
    - Auto-orient using EXIF orientation
    - Resize to max long edge (only shrink)
    - Strip metadata (save without EXIF)
    
    Args:
        src_path: Source image path
        dst_path: Destination JPEG path
        max_long_edge: Maximum long edge in pixels (only shrink, never enlarge)
        quality: JPEG quality (1-100)
        resampling: Resampling algorithm (default: BILINEAR for thumbnails <=512px, LANCZOS for larger)
    """
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Choose resampling algorithm: faster BILINEAR for small outputs, high-quality LANCZOS for larger
    if resampling is None:
        if max_long_edge <= 512:
            resampling = Image.Resampling.BILINEAR  # Faster for thumbnails, minimal quality loss
        else:
            resampling = Image.Resampling.LANCZOS  # High quality for share images
    
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
                im = im.resize(new_size, resampling)

            im.save(
                dst_path,
                format="JPEG",
                quality=int(quality),
                optimize=True,
                progressive=True,
            )
    except Exception as e:  # noqa: BLE001 - we want a clean error surface
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Provide more specific guidance for common errors
        if "cannot identify image file" in error_msg.lower() or "cannot open" in error_msg.lower():
            guidance = (
                f"  This file may not be a valid image, or the file is corrupted.\n"
                f"  Try: Verify the source file is a valid image format (JPEG, PNG, etc.)"
            )
        elif "permission denied" in error_msg.lower() or "access denied" in error_msg.lower():
            guidance = (
                f"  Cannot write to destination directory.\n"
                f"  Try: Check write permissions for {dst_path.parent}"
            )
        elif "no space left" in error_msg.lower() or "disk full" in error_msg.lower():
            guidance = (
                f"  Out of disk space.\n"
                f"  Try: Free up space or change the output directory"
            )
        else:
            guidance = f"  Error type: {error_type}"
        
        raise ProcessingError(
            f"Failed to process image: {src_path.name}\n"
            f"  Source: {src_path}\n"
            f"  Destination: {dst_path}\n"
            f"{guidance}\n"
            f"  Original error: {error_msg}"
        ) from e


