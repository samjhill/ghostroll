"""
Automatic lighting enhancement similar to Lightroom's auto-settings.

This module implements histogram-based auto-adjustments for:
- Exposure
- Contrast
- Highlights/Shadows
- Whites/Blacks
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps


def auto_exposure_adjust(image: Image.Image) -> float:
    """
    Calculate auto exposure adjustment based on histogram.
    
    Returns exposure adjustment in EV (exposure value) units.
    Positive values brighten, negative values darken.
    """
    # Convert to grayscale for histogram analysis
    gray = image.convert("L")
    hist = np.array(gray.histogram())
    
    # Normalize histogram
    hist = hist.astype(np.float32)
    hist /= hist.sum()
    
    # Calculate weighted mean (center of mass)
    bins = np.arange(256)
    mean = np.sum(bins * hist)
    
    # Target mean for well-exposed image (slightly brighter than middle gray)
    target_mean = 128.0
    
    # Calculate exposure adjustment
    # If mean is too dark (< 100), brighten
    # If mean is too bright (> 180), darken
    if mean < 100:
        ev_adjust = (target_mean - mean) / 128.0
    elif mean > 180:
        ev_adjust = (target_mean - mean) / 128.0
    else:
        ev_adjust = 0.0
    
    # Clamp to reasonable range (-2 to +2 EV)
    ev_adjust = max(-2.0, min(2.0, ev_adjust))
    
    return ev_adjust


def auto_contrast_adjust(image: Image.Image) -> tuple[float, float]:
    """
    Calculate auto contrast adjustment (black point and white point).
    
    Returns (black_point, white_point) as values 0-255.
    Uses histogram clipping to find optimal black/white points.
    """
    gray = image.convert("L")
    hist = np.array(gray.histogram())
    
    # Normalize
    hist = hist.astype(np.float32)
    hist /= hist.sum()
    
    # Cumulative distribution
    cumsum = np.cumsum(hist)
    
    # Find black point: 0.5% of pixels should be pure black
    black_point = 0
    for i in range(256):
        if cumsum[i] >= 0.005:
            black_point = i
            break
    
    # Find white point: 0.5% of pixels should be pure white
    white_point = 255
    for i in range(255, -1, -1):
        if cumsum[i] <= 0.995:
            white_point = i
            break
    
    # If range is too narrow, don't adjust
    if white_point - black_point < 50:
        return 0.0, 255.0
    
    return float(black_point), float(white_point)


def auto_highlights_shadows(image: Image.Image) -> tuple[float, float]:
    """
    Calculate auto highlights and shadows adjustment.
    
    Returns (highlights_adjust, shadows_adjust) as values -100 to +100.
    Positive highlights = reduce highlights (darken bright areas)
    Positive shadows = brighten shadows (lighten dark areas)
    """
    gray = image.convert("L")
    pixels = np.array(gray, dtype=np.float32)
    
    # Analyze bright areas (highlights)
    bright_mask = pixels > 200
    bright_pct = np.sum(bright_mask) / pixels.size
    
    # Analyze dark areas (shadows)
    dark_mask = pixels < 50
    dark_pct = np.sum(dark_mask) / pixels.size
    
    # Calculate adjustments
    # If too many bright pixels, reduce highlights
    highlights_adjust = 0.0
    if bright_pct > 0.15:  # More than 15% very bright
        highlights_adjust = min(50.0, (bright_pct - 0.15) * 200.0)
    
    # If too many dark pixels, brighten shadows
    shadows_adjust = 0.0
    if dark_pct > 0.20:  # More than 20% very dark
        shadows_adjust = min(50.0, (dark_pct - 0.20) * 200.0)
    
    return highlights_adjust, shadows_adjust


def apply_exposure(image: Image.Image, ev_adjust: float) -> Image.Image:
    """
    Apply exposure adjustment to image.
    
    EV adjustment: +1 EV = double brightness, -1 EV = half brightness.
    """
    if abs(ev_adjust) < 0.01:
        return image
    
    # Convert EV to multiplier
    multiplier = 2.0 ** ev_adjust
    
    # Apply using ImageOps
    # Convert to numpy for precise control
    img_array = np.array(image, dtype=np.float32)
    img_array *= multiplier
    
    # Clip to valid range
    img_array = np.clip(img_array, 0, 255)
    
    # Convert back to PIL Image
    result = Image.fromarray(img_array.astype(np.uint8))
    
    # Preserve mode
    if image.mode != result.mode:
        result = result.convert(image.mode)
    
    return result


def apply_contrast(image: Image.Image, black_point: float, white_point: float) -> Image.Image:
    """
    Apply contrast adjustment using black/white point mapping.
    """
    if black_point == 0.0 and white_point == 255.0:
        return image
    
    # Convert to numpy
    img_array = np.array(image, dtype=np.float32)
    
    # Linear mapping: map [black_point, white_point] to [0, 255]
    if white_point > black_point:
        scale = 255.0 / (white_point - black_point)
        offset = -black_point * scale
        img_array = img_array * scale + offset
    
    # Clip to valid range
    img_array = np.clip(img_array, 0, 255)
    
    # Convert back
    result = Image.fromarray(img_array.astype(np.uint8))
    
    # Preserve mode
    if image.mode != result.mode:
        result = result.convert(image.mode)
    
    return result


def apply_highlights_shadows(
    image: Image.Image, highlights: float, shadows: float
) -> Image.Image:
    """
    Apply highlights and shadows adjustment.
    
    This is a simplified version. A full implementation would use
    tone mapping or local adjustments, but for Lambda we'll use
    a global curve adjustment.
    """
    if abs(highlights) < 0.1 and abs(shadows) < 0.1:
        return image
    
    # Convert to numpy
    img_array = np.array(image, dtype=np.float32)
    
    # Normalize to 0-1
    img_norm = img_array / 255.0
    
    # Apply curve adjustments
    # Highlights: reduce bright areas (compress highlights)
    if highlights > 0:
        # Create a curve that reduces values above 0.7
        bright_mask = img_norm > 0.7
        reduction = highlights / 100.0 * 0.3  # Max 30% reduction
        img_norm[bright_mask] = img_norm[bright_mask] - (
            (img_norm[bright_mask] - 0.7) * reduction
        )
    
    # Shadows: brighten dark areas (lift shadows)
    if shadows > 0:
        # Create a curve that lifts values below 0.3
        dark_mask = img_norm < 0.3
        lift = shadows / 100.0 * 0.2  # Max 20% lift
        img_norm[dark_mask] = img_norm[dark_mask] + (
            (0.3 - img_norm[dark_mask]) * lift
        )
    
    # Convert back to 0-255
    img_array = np.clip(img_norm * 255.0, 0, 255)
    
    # Convert back to PIL
    result = Image.fromarray(img_array.astype(np.uint8))
    
    # Preserve mode
    if image.mode != result.mode:
        result = result.convert(image.mode)
    
    return result


def enhance_image_auto(image: Image.Image) -> Image.Image:
    """
    Apply automatic lighting enhancements similar to Lightroom's auto-settings.
    
    This function:
    1. Analyzes the image histogram
    2. Calculates optimal adjustments
    3. Applies exposure, contrast, highlights, and shadows adjustments
    
    Args:
        image: PIL Image to enhance
        
    Returns:
        Enhanced PIL Image
    """
    # Ensure we're working with RGB
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")
    
    # Calculate auto adjustments
    ev_adjust = auto_exposure_adjust(image)
    black_point, white_point = auto_contrast_adjust(image)
    highlights, shadows = auto_highlights_shadows(image)
    
    # Apply adjustments in order
    result = image
    
    # 1. Exposure first (affects overall brightness)
    if abs(ev_adjust) > 0.01:
        result = apply_exposure(result, ev_adjust)
    
    # 2. Contrast (black/white point mapping)
    if black_point > 0 or white_point < 255:
        result = apply_contrast(result, black_point, white_point)
    
    # 3. Highlights and shadows (fine-tuning)
    if abs(highlights) > 0.1 or abs(shadows) > 0.1:
        result = apply_highlights_shadows(result, highlights, shadows)
    
    return result

