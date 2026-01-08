#!/usr/bin/env python3
"""Test the fixed battery indicator visibility."""

from pathlib import Path
from ghostroll.status import Status, StatusWriter

def test_fixed_battery():
    """Generate test images with the fixed battery indicator."""
    output_dir = Path("test_battery_fixed")
    output_dir.mkdir(exist_ok=True)
    
    # Test small display (250x122)
    writer = StatusWriter(
        json_path=output_dir / "status.json",
        image_path=output_dir / "status.png",
        image_size=(250, 122)
    )
    
    test_cases = [
        (100, False, "Full battery"),
        (75, True, "Charging 75%"),
        (50, False, "Half battery"),
        (25, False, "Quarter battery"),
        (15, False, "Low battery"),
        (5, True, "Very low charging"),
    ]
    
    print("Generating test images with improved battery indicator...")
    print()
    
    for pct, charging, desc in test_cases:
        status = Status(
            state="idle",
            step="",
            message=desc,
            battery_percentage=pct,
            battery_charging=charging,
        )
        
        writer.image_path = output_dir / f"battery_{pct}pct_{'charging' if charging else 'not_charging'}.png"
        writer.write(status)
        
        # Calculate expected position
        battery_size = 24
        text_width = 20 if pct < 100 else 25
        total_width = battery_size + 3 + 4 + text_width
        battery_x = 250 - total_width - 4
        
        print(f"  ✓ {desc}: {pct}% {'(charging)' if charging else ''}")
        print(f"    Position: x={battery_x}, size={battery_size}px")
        print(f"    File: {writer.image_path.name}")
    
    print()
    print(f"All images generated in: {output_dir.absolute()}")
    print("Check the PNG files to verify battery indicators are visible!")

if __name__ == "__main__":
    test_fixed_battery()



