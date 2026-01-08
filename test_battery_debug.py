#!/usr/bin/env python3
"""Debug script to test battery indicator visibility."""

from pathlib import Path
from ghostroll.status import Status, StatusWriter

def test_battery_visibility():
    """Generate test images to debug battery indicator."""
    output_dir = Path("test_battery_debug")
    output_dir.mkdir(exist_ok=True)
    
    # Test small display
    writer = StatusWriter(
        json_path=output_dir / "status.json",
        image_path=output_dir / "status.png",
        image_size=(250, 122)
    )
    
    # Test with battery
    status = Status(
        state="idle",
        step="",
        message="Testing battery indicator",
        battery_percentage=75,
        battery_charging=False,
    )
    
    writer.write(status)
    
    print(f"Generated test image: {output_dir / 'status.png'}")
    print(f"Display size: 250x122")
    print(f"Battery should be at: x={250 - 50} = 200, y=4")
    print(f"Battery size: 18px wide")
    print(f"Battery should extend to: x={200 + 18 + 2} = 220 (plus text)")
    
    # Also test with different percentages
    for pct in [100, 75, 50, 25, 10]:
        status2 = Status(
            state="idle",
            step="",
            message=f"Battery {pct}%",
            battery_percentage=pct,
            battery_charging=False,
        )
        writer.image_path = output_dir / f"battery_{pct}.png"
        writer.write(status2)
        print(f"  Generated: battery_{pct}.png")

if __name__ == "__main__":
    test_battery_visibility()



