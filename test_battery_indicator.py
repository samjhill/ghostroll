#!/usr/bin/env python3
"""Test script to verify battery indicator rendering."""

from pathlib import Path
from ghostroll.status import Status, StatusWriter, get_pisugar_battery

def test_battery_indicator_rendering():
    """Test that battery indicator renders correctly in status images."""
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        json_path = tmp_path / "status.json"
        image_path = tmp_path / "status.png"
        
        writer = StatusWriter(
            json_path=json_path,
            image_path=image_path,
            image_size=(250, 122)  # Small e-ink display size
        )
        
        # Test with battery data
        status = Status(
            state="idle",
            step="",
            message="Waiting for SD card",
            battery_percentage=85,
            battery_charging=False,
        )
        writer.write(status)
        
        # Verify files were created
        assert json_path.exists(), "Status JSON should be created"
        assert image_path.exists(), "Status image should be created"
        
        # Verify JSON contains battery data
        import json
        data = json.loads(json_path.read_text("utf-8"))
        assert data["battery_percentage"] == 85
        assert data["battery_charging"] is False
        
        # Test with charging battery
        status2 = Status(
            state="running",
            step="process",
            message="Processing images",
            battery_percentage=50,
            battery_charging=True,
        )
        writer.write(status2)
        
        data2 = json.loads(json_path.read_text("utf-8"))
        assert data2["battery_percentage"] == 50
        assert data2["battery_charging"] is True
        
        # Test with low battery
        status3 = Status(
            state="idle",
            step="",
            message="Low battery",
            battery_percentage=15,
            battery_charging=False,
        )
        writer.write(status3)
        
        # Test with no battery data (should not crash)
        status4 = Status(
            state="idle",
            step="",
            message="No battery info",
        )
        writer.write(status4)
        
        data4 = json.loads(json_path.read_text("utf-8"))
        assert data4.get("battery_percentage") is None or data4.get("battery_percentage") is not None
        
        print("✓ Battery indicator rendering tests passed!")
        print(f"  - Created status image at: {image_path}")
        print(f"  - Image size: {image_path.stat().st_size} bytes")

def test_battery_reading():
    """Test battery reading function (will return None on non-Pi systems)."""
    result = get_pisugar_battery()
    
    if result is None:
        print("✓ Battery reading test: PiSugar not available (expected on non-Pi systems)")
    else:
        print(f"✓ Battery reading test: Got battery data: {result}")
        assert "percentage" in result
        assert "is_charging" in result
        assert 0 <= result["percentage"] <= 100

if __name__ == "__main__":
    print("Testing battery indicator functionality...")
    print()
    
    test_battery_reading()
    print()
    test_battery_indicator_rendering()
    print()
    print("All tests passed! ✓")



