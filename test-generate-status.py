#!/usr/bin/env python3
"""Generate a test status.png with the updated positioning."""

import sys
from pathlib import Path

# Add the project to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ghostroll.status import Status, StatusWriter

def main():
    status_path = Path.home() / "ghostroll" / "status.json"
    image_path = Path.home() / "ghostroll" / "status.png"
    
    # Create directory if needed
    image_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create StatusWriter with small display size to trigger the small display layout
    writer = StatusWriter(
        json_path=status_path,
        image_path=image_path,
        image_size=(250, 122),  # e-ink display size
    )
    
    # Create a test status
    status = Status(
        state="IDLE",
        step="idle",
        message="Waiting for SD card",
        ip="192.168.1.100",  # Example IP
        hostname="ghostroll-pi",
    )
    
    print(f"Generating status image at {image_path}")
    print(f"Using image size: {writer.image_size}")
    writer.write(status)
    print(f"✓ Generated {image_path}")
    print(f"\nNow run: ./test-eink-local.sh")

if __name__ == "__main__":
    main()

