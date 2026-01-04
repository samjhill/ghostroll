#!/usr/bin/env python3
"""Quick diagnostic script to check status.png content."""

import sys
from pathlib import Path
from PIL import Image

def main():
    status_png = Path("/home/pi/ghostroll/status.png")
    
    if not status_png.exists():
        print(f"ERROR: {status_png} does not exist")
        return 1
    
    print(f"Checking: {status_png}")
    print(f"File size: {status_png.stat().st_size} bytes")
    
    try:
        img = Image.open(status_png)
        print(f"Image size: {img.size}")
        print(f"Image mode: {img.mode}")
        
        # Convert to a format we can analyze
        if img.mode == "1":
            pixels = list(img.getdata())
            black = sum(1 for p in pixels if p == 0)
            white = sum(1 for p in pixels if p != 0)
            total = len(pixels)
            black_pct = (black / total * 100) if total > 0 else 0
            print(f"1-bit mode: {black} black ({black_pct:.1f}%), {white} white")
        elif img.mode == "L":
            pixels = list(img.getdata())
            # Count pixels darker than 128 (potential text)
            dark = sum(1 for p in pixels if p < 128)
            light = sum(1 for p in pixels if p >= 128)
            total = len(pixels)
            dark_pct = (dark / total * 100) if total > 0 else 0
            print(f"Grayscale mode: {dark} dark pixels ({dark_pct:.1f}%), {light} light pixels")
            # Show pixel value distribution
            min_val = min(pixels) if pixels else 0
            max_val = max(pixels) if pixels else 255
            avg_val = sum(pixels) / len(pixels) if pixels else 0
            print(f"  Pixel range: {min_val}-{max_val}, average: {avg_val:.1f}")
        else:
            print(f"Mode {img.mode} - converting to grayscale for analysis")
            img_gray = img.convert("L")
            pixels = list(img_gray.getdata())
            dark = sum(1 for p in pixels if p < 128)
            total = len(pixels)
            dark_pct = (dark / total * 100) if total > 0 else 0
            print(f"After conversion: {dark} dark pixels ({dark_pct:.1f}%)")
        
        # Check if image appears to have content
        if img.mode == "1":
            if black == 0:
                print("\n⚠️  WARNING: Image is all white - no text/content detected!")
            elif black_pct < 1:
                print(f"\n⚠️  WARNING: Very little content ({black_pct:.1f}% black) - text may not be visible")
            else:
                print(f"\n✓ Image appears to have content ({black_pct:.1f}% black pixels)")
        elif img.mode == "L":
            if dark_pct < 1:
                print(f"\n⚠️  WARNING: Very little dark content ({dark_pct:.1f}%) - text may not be visible")
                if avg_val > 240:
                    print("   Image appears to be mostly white/light")
            else:
                print(f"\n✓ Image appears to have content ({dark_pct:.1f}% dark pixels)")
        
        return 0
        
    except Exception as e:
        print(f"ERROR reading image: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())

