#!/usr/bin/env python3
"""
Generate realistic test JPEG images for GhostRoll ingest testing.

Creates unique, realistically-sized JPEG images (2-8MB each) and places them
in the DCIM folder structure on the SD card.
"""

import argparse
import os
import random
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np


def generate_realistic_jpeg(
    output_path: Path,
    width: int = 4000,
    height: int = 3000,
    quality: int = 95,
    seed: int | None = None,
) -> int:
    """
    Generate a realistic JPEG image with random content.
    
    Args:
        output_path: Where to save the JPEG
        width: Image width in pixels
        height: Image height in pixels
        quality: JPEG quality (85-100)
        seed: Random seed for reproducibility (uses random if None)
    
    Returns:
        Size of the generated file in bytes
    """
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
    
    # Create a base image with some realistic content
    # Use a gradient background with some random shapes/textures
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)
    
    # Add a gradient-like background with random colors
    base_color = (
        random.randint(200, 255),
        random.randint(200, 255),
        random.randint(200, 255)
    )
    
    # Draw some random shapes to simulate a photo
    for _ in range(random.randint(5, 15)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        
        # Ensure x1 < x2 and y1 < y2 for shapes
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        
        color = (
            random.randint(0, 255),
            random.randint(0, 255),
            random.randint(0, 255)
        )
        
        shape_type = random.choice(['ellipse', 'rectangle', 'line'])
        if shape_type == 'ellipse':
            # Ensure minimum size for ellipse
            if x2 - x1 < 10:
                x2 = x1 + 10
            if y2 - y1 < 10:
                y2 = y1 + 10
            draw.ellipse([x1, y1, x2, y2], fill=color, outline=None)
        elif shape_type == 'rectangle':
            # Ensure minimum size for rectangle
            if x2 - x1 < 10:
                x2 = x1 + 10
            if y2 - y1 < 10:
                y2 = y1 + 10
            draw.rectangle([x1, y1, x2, y2], fill=color, outline=None)
        else:
            # For lines, coordinates can be in any order
            draw.line([x1, y1, x2, y2], fill=color, width=random.randint(1, 10))
    
    # Add some text to make it more unique
    try:
        # Try to use a system font
        font_size = random.randint(50, 200)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
            except:
                font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()
    
    text = f"TEST-{random.randint(1000, 9999)}"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = random.randint(0, max(1, width - text_width))
    y = random.randint(0, max(1, height - text_height))
    
    text_color = (
        random.randint(0, 100),
        random.randint(0, 100),
        random.randint(0, 100)
    )
    draw.text((x, y), text, fill=text_color, font=font)
    
    # Add some noise/texture to make file size more realistic
    # Convert to numpy array for manipulation
    img_array = np.array(img)
    
    # Add subtle noise
    noise = np.random.randint(-10, 10, img_array.shape, dtype=np.int16)
    img_array = np.clip(img_array.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(img_array)
    
    # Save as JPEG with specified quality
    img.save(output_path, 'JPEG', quality=quality, optimize=True)
    
    return output_path.stat().st_size


def find_sd_card() -> Path | None:
    """Find the SD card mounted at /Volumes/auto-import or similar."""
    base_volumes = Path("/Volumes")
    
    # Check for exact match first
    exact_match = base_volumes / "auto-import"
    if exact_match.exists() and exact_match.is_dir():
        return exact_match
    
    # Check for prefix matches
    for vol in base_volumes.iterdir():
        if vol.name.startswith("auto-import"):
            return vol
    
    return None


def get_dcim_folder(sd_root: Path) -> Path:
    """Get or create the DCIM folder structure."""
    dcim = sd_root / "DCIM"
    
    if not dcim.exists():
        dcim.mkdir(parents=True, exist_ok=True)
    
    # Check for existing camera folders (like 100MSDCF, 100CANON, etc.)
    existing_folders = [d for d in dcim.iterdir() if d.is_dir() and d.name.isdigit()]
    
    if existing_folders:
        # Use the first existing folder
        return existing_folders[0]
    else:
        # Create a typical camera folder (100MSDCF is Sony, 100CANON is Canon)
        camera_folder = dcim / "100MSDCF"
        camera_folder.mkdir(parents=True, exist_ok=True)
        return camera_folder


def generate_filename(index: int, existing_files: set[str]) -> str:
    """Generate a unique camera-style filename."""
    # Try common camera naming patterns
    patterns = [
        f"IMG_{index:04d}.JPG",
        f"DSC_{index:05d}.JPG",
        f"IMG_{index:04d}.jpg",
        f"DSC_{index:05d}.jpg",
    ]
    
    for pattern in patterns:
        if pattern not in existing_files:
            return pattern
    
    # Fallback to timestamp-based name
    import time
    timestamp = int(time.time() * 1000) % 1000000
    return f"IMG_{timestamp}_{index:04d}.JPG"


def main():
    parser = argparse.ArgumentParser(
        description="Generate test JPEG images for GhostRoll ingest testing"
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=20,
        help="Number of images to generate (default: 20)"
    )
    parser.add_argument(
        "--sd-path",
        type=str,
        help="Path to SD card (default: auto-detect /Volumes/auto-import)"
    )
    parser.add_argument(
        "--min-size-mb",
        type=float,
        default=2.0,
        help="Minimum file size in MB (default: 2.0)"
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        default=8.0,
        help="Maximum file size in MB (default: 8.0)"
    )
    
    args = parser.parse_args()
    
    # Find SD card
    if args.sd_path:
        sd_root = Path(args.sd_path)
        if not sd_root.exists():
            print(f"Error: SD card path does not exist: {sd_root}", file=sys.stderr)
            sys.exit(1)
    else:
        sd_root = find_sd_card()
        if sd_root is None:
            print("Error: Could not find SD card at /Volumes/auto-import", file=sys.stderr)
            print("Please specify --sd-path or ensure the card is mounted", file=sys.stderr)
            sys.exit(1)
    
    print(f"Found SD card at: {sd_root}")
    
    # Get DCIM folder
    dcim_folder = get_dcim_folder(sd_root)
    print(f"Using DCIM folder: {dcim_folder}")
    
    # Get existing files to avoid duplicates
    existing_files = {f.name for f in dcim_folder.iterdir() if f.is_file()}
    print(f"Found {len(existing_files)} existing files in DCIM folder")
    
    # Generate images
    print(f"\nGenerating {args.count} test images...")
    
    generated = []
    for i in range(args.count):
        filename = generate_filename(i + 1, existing_files)
        output_path = dcim_folder / filename
        
        # Vary image dimensions and quality to achieve target file sizes
        # Larger images with higher quality = larger file size
        target_size_mb = random.uniform(args.min_size_mb, args.max_size_mb)
        
        # Adjust dimensions and quality based on target size
        if target_size_mb < 3.0:
            width, height = 3000, 2000
            quality = random.randint(85, 90)
        elif target_size_mb < 5.0:
            width, height = 4000, 3000
            quality = random.randint(90, 95)
        else:
            width, height = 6000, 4000
            quality = random.randint(95, 98)
        
        # Generate the image
        file_size_bytes = generate_realistic_jpeg(
            output_path,
            width=width,
            height=height,
            quality=quality,
            seed=random.randint(0, 1000000)
        )
        
        file_size_mb = file_size_bytes / (1024 * 1024)
        generated.append((filename, file_size_mb))
        existing_files.add(filename)
        
        print(f"  [{i+1}/{args.count}] {filename} - {file_size_mb:.2f} MB")
    
    print(f"\n✅ Successfully generated {len(generated)} images")
    print(f"   Total size: {sum(size for _, size in generated):.2f} MB")
    print(f"   Location: {dcim_folder}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

