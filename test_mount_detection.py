#!/usr/bin/env python3
"""
Quick test script for mount detection - run this directly on the Pi to test changes.

Usage:
    # On your local machine, sync and run:
    ./pi/scripts/quick-deploy.sh raspberrypi
    ssh raspberrypi "cd /usr/local/src/ghostroll && python3 test_mount_detection.py"
    
    # Or directly on the Pi:
    cd /usr/local/src/ghostroll
    python3 test_mount_detection.py

This tests the mount detection logic without needing to restart the service.
"""

import sys
from pathlib import Path

# Add the project to the path
sys.path.insert(0, str(Path(__file__).parent))

from ghostroll.volume_watch import find_candidate_mounts, pick_mount_with_dcim, _is_volume_accessible, _is_actually_mounted
from ghostroll.config import load_config
import logging
import subprocess

# Set up logging to see what's happening
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)

def check_findmnt():
    """Check if findmnt is available."""
    try:
        result = subprocess.run(["findmnt", "--version"], capture_output=True, timeout=2)
        return result.returncode == 0
    except:
        return False

def main():
    print("=" * 60)
    print("Testing mount detection for 'auto-import'")
    print("=" * 60)
    
    # Check prerequisites
    print("\n0. Checking prerequisites...")
    has_findmnt = check_findmnt()
    print(f"   - findmnt available: {has_findmnt}")
    if not has_findmnt:
        print("   ⚠️  WARNING: findmnt not found, mount detection may be less reliable")
    
    cfg = load_config()
    mount_roots = [Path(p) for p in cfg.mount_roots.split(",") if p.strip()]
    
    print(f"\n1. Checking mount roots: {mount_roots}")
    
    # Test finding candidates
    print("\n2. Finding candidate mounts...")
    candidates = find_candidate_mounts(mount_roots, label="auto-import", verbose=True)
    print(f"   Found {len(candidates)} candidates: {candidates}")
    
    # Test each candidate
    for candidate in candidates:
        print(f"\n3. Testing candidate: {candidate}")
        print(f"   - Exists: {candidate.exists()}")
        print(f"   - Is dir: {candidate.is_dir()}")
        
        # Check if actually mounted
        is_mounted = _is_actually_mounted(candidate)
        print(f"   - Is mounted: {is_mounted}")
        
        if is_mounted:
            # Show mount details
            try:
                result = subprocess.run(
                    ["findmnt", "-n", "-o", "FSTYPE,SOURCE", str(candidate)],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    print(f"   - Mount details: {result.stdout.strip()}")
            except:
                pass
        
        # Check if accessible
        is_accessible = _is_volume_accessible(candidate)
        print(f"   - Is accessible: {is_accessible}")
        
        # Check for DCIM
        dcim = candidate / "DCIM"
        print(f"   - DCIM exists: {dcim.exists()}")
        if dcim.exists():
            try:
                items = list(dcim.iterdir())
                print(f"   - DCIM items: {len(items)}")
                if items:
                    print(f"   - Sample: {items[0].name}")
            except Exception as e:
                print(f"   - DCIM error: {e}")
    
    # Test the main function
    print("\n4. Testing pick_mount_with_dcim...")
    vol = pick_mount_with_dcim(mount_roots, label="auto-import", verbose=True)
    if vol:
        print(f"   ✓ Found volume with DCIM: {vol}")
    else:
        print("   ✗ No volume with DCIM found")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
    print("\n💡 Tip: Run this script after making changes to test without restarting the service")
    print("   Local: ./pi/scripts/quick-deploy.sh && ssh pi 'cd /usr/local/src/ghostroll && python3 test_mount_detection.py'")

if __name__ == "__main__":
    main()

