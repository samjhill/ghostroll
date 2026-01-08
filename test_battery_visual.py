#!/usr/bin/env python3
"""Visual test to generate status images with battery indicators."""

from pathlib import Path
from ghostroll.status import Status, StatusWriter

def generate_test_images():
    """Generate test status images with various battery states."""
    output_dir = Path("test_battery_output")
    output_dir.mkdir(exist_ok=True)
    
    # Test small display (250x122) - typical e-ink size
    writer_small = StatusWriter(
        json_path=output_dir / "status_small.json",
        image_path=output_dir / "status_small.png",
        image_size=(250, 122)
    )
    
    # Test large display (800x480)
    writer_large = StatusWriter(
        json_path=output_dir / "status_large.json",
        image_path=output_dir / "status_large.png",
        image_size=(800, 480)
    )
    
    test_cases = [
        {
            "name": "idle_full_battery",
            "status": Status(
                state="idle",
                step="",
                message="Waiting for SD card",
                battery_percentage=100,
                battery_charging=False,
            )
        },
        {
            "name": "idle_charging",
            "status": Status(
                state="idle",
                step="",
                message="Waiting for SD card",
                battery_percentage=75,
                battery_charging=True,
            )
        },
        {
            "name": "running_medium_battery",
            "status": Status(
                state="running",
                step="process",
                message="Processing images",
                battery_percentage=50,
                battery_charging=False,
                counts={"discovered": 25, "new": 10, "processed": 5},
            )
        },
        {
            "name": "running_low_battery",
            "status": Status(
                state="running",
                step="upload",
                message="Uploading photos",
                battery_percentage=15,
                battery_charging=False,
                counts={"uploaded_done": 3, "uploaded_total": 10},
            )
        },
        {
            "name": "done_no_battery_info",
            "status": Status(
                state="done",
                step="done",
                message="Complete. Remove SD card now",
                session_id="test-session-12345",
            )
        },
    ]
    
    print(f"Generating test images in {output_dir}/...")
    print()
    
    for i, test_case in enumerate(test_cases):
        name = test_case["name"]
        status = test_case["status"]
        
        # Generate small display version
        writer_small.json_path = output_dir / f"status_small_{name}.json"
        writer_small.image_path = output_dir / f"status_small_{name}.png"
        writer_small.write(status)
        
        # Generate large display version
        writer_large.json_path = output_dir / f"status_large_{name}.json"
        writer_large.image_path = output_dir / f"status_large_{name}.png"
        writer_large.write(status)
        
        battery_info = ""
        if status.battery_percentage is not None:
            battery_info = f" (Battery: {status.battery_percentage}%, Charging: {status.battery_charging})"
        
        print(f"  ✓ Generated: {name}{battery_info}")
    
    print()
    print(f"All test images generated in: {output_dir.absolute()}")
    print("You can open the PNG files to visually verify the battery indicators.")

if __name__ == "__main__":
    generate_test_images()



