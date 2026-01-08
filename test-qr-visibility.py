#!/usr/bin/env python3
"""Test QR code visibility in DONE state."""

import sys
from pathlib import Path

# Add the project to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ghostroll.status import Status, StatusWriter
from ghostroll.qr import write_qr_png

def main():
    status_path = Path.home() / "ghostroll" / "status.json"
    image_path = Path.home() / "ghostroll" / "status.png"
    qr_path = Path.home() / "ghostroll" / "test-qr.png"
    
    # Create directories if needed
    image_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Generate a test QR code
    print("Generating test QR code...")
    write_qr_png(data="https://example.com/share/abc123", out_path=qr_path)
    print(f"✓ Generated QR code at {qr_path}")
    
    # Create StatusWriter with small display size to trigger the small display layout
    writer = StatusWriter(
        json_path=status_path,
        image_path=image_path,
        image_size=(250, 122),  # e-ink display size
    )
    
    # Create a DONE status with QR code
    status = Status(
        state="done",
        step="done",
        message="Done! Remove card",
        session_id="test-session-123456789",
        volume="/media/test-card",
        counts={
            "discovered": 10,
            "new": 5,
            "processed": 5,
            "uploaded": 5,
        },
        url="https://example.com/share/abc123",
        qr_path=str(qr_path),
        ip="192.168.1.100",
        hostname="ghostroll-pi",
    )
    
    print(f"\nGenerating status image at {image_path}")
    print(f"Using image size: {writer.image_size}")
    print(f"State: {status.state}")
    print(f"QR path: {status.qr_path}")
    writer.write(status)
    print(f"✓ Generated {image_path}")
    
    # Now test the e-ink processing
    print("\n" + "="*60)
    print("Testing e-ink processing...")
    print("="*60)
    
    import os
    os.environ["GHOSTROLL_EINK_TEST_MODE"] = "1"
    os.environ["GHOSTROLL_STATUS_IMAGE_PATH"] = str(image_path)
    os.environ["GHOSTROLL_EINK_TEST_OUTPUT"] = str(Path.home() / "ghostroll" / "status-eink-processed.png")
    os.environ["GHOSTROLL_EINK_WIDTH"] = "250"
    os.environ["GHOSTROLL_EINK_HEIGHT"] = "122"
    
    # Run the e-ink script directly
    eink_script = project_root / "pi" / "scripts" / "ghostroll-eink-waveshare213v4.py"
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, str(eink_script)],
            env=os.environ,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"E-ink script returned {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            if result.stdout:
                print(f"Output: {result.stdout}")
            return 1
        output_path = Path(os.environ["GHOSTROLL_EINK_TEST_OUTPUT"])
        if output_path.exists():
            print(f"\n✓ E-ink processed image saved to: {output_path}")
            print(f"\nOpen the image to verify QR code is visible:")
            print(f"  open {output_path}")
            
            # Check pixel stats
            from PIL import Image
            img = Image.open(output_path)
            pixels = list(img.getdata())
            black_pixels = sum(1 for p in pixels if p == 0)
            total_pixels = len(pixels)
            black_pct = (black_pixels / total_pixels * 100) if total_pixels > 0 else 0
            print(f"\nProcessed image stats:")
            print(f"  Size: {img.size}")
            print(f"  Mode: {img.mode}")
            print(f"  Black pixels: {black_pixels} ({black_pct:.1f}%)")
            if black_pct < 1.0:
                print(f"  ⚠️  WARNING: Very few black pixels - QR code may not be visible!")
            else:
                print(f"  ✓ Good black pixel density - QR code should be visible")
        else:
            print(f"\n✗ E-ink processed image not found at {output_path}")
            return 1
    except Exception as e:
        print(f"\n✗ Error running e-ink processing: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "="*60)
    print("Test complete!")
    print("="*60)
    return 0

if __name__ == "__main__":
    sys.exit(main())

