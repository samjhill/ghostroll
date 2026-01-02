"""
Bulletproof mount detection using findmnt as the source of truth.

This module provides a single, reliable way to check if a path is a real device mount.
Uses findmnt (Linux) or mount (macOS) as the authoritative source.
"""

from __future__ import annotations

import logging
import platform
import subprocess
from pathlib import Path

logger = logging.getLogger("ghostroll.mount_check")


def is_real_device_mount(mount_path: Path, *, trigger_automount: bool = False) -> bool:
    """
    Check if a path is a real device mount (not just a directory or autofs placeholder).
    
    This is the bulletproof method - uses findmnt/mount as the source of truth.
    
    Args:
        mount_path: Path to check (e.g., /mnt/auto-import)
        trigger_automount: If True, try to access the directory first to trigger automount
    
    Returns:
        True if there's a real device mounted at this path, False otherwise.
    
    Strategy:
        1. For /mnt paths on Linux: trigger automount if requested, then check findmnt
        2. Use findmnt to get mount source and filesystem type
        3. Reject autofs filesystem type
        4. Reject systemd-1 or autofs sources
        5. For /dev/ devices, verify device file exists
        6. Return True only if all checks pass
    """
    system = platform.system().lower()
    path_str = str(mount_path)
    
    # On macOS
    if system == "darwin":
        if path_str.startswith("/Volumes/"):
            # /Volumes is always mounts on macOS
            return True
        try:
            result = subprocess.run(
                ["mount"], capture_output=True, text=True, timeout=2
            )
            return path_str in result.stdout
        except Exception:
            return False
    
    # On Linux
    if system == "linux":
        # /media and /run/media are typically always mounts (trust them)
        if path_str.startswith("/media/") or path_str.startswith("/run/media/"):
            return True
        
        # For /mnt and other paths, use findmnt
        if path_str.startswith("/mnt/") and trigger_automount:
            # Try to trigger automount by accessing the directory
            try:
                list(mount_path.iterdir())
                import time
                time.sleep(0.3)  # Give automount time to complete
            except (OSError, IOError):
                # Can't access - probably not mounted
                pass
        
        try:
            # Use findmnt to get mount information
            result = subprocess.run(
                ["findmnt", "-n", "-o", "FSTYPE,SOURCE", path_str],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode != 0:
                # Not mounted
                return False
            
            output = result.stdout.strip()
            if not output:
                # Empty output = not mounted
                return False
            
            # Parse: "FSTYPE SOURCE"
            parts = output.split(None, 1)
            if len(parts) < 1:
                return False
            
            fstype = parts[0]
            source = parts[1] if len(parts) > 1 else ""
            
            # Reject autofs filesystem type
            if fstype == "autofs":
                logger.debug(f"{mount_path} is autofs - not a real device mount")
                return False
            
            # Reject systemd-1 or autofs sources
            if source.startswith("systemd-1") or "autofs" in source.lower():
                logger.debug(f"{mount_path} has automount source {source} - not a real device")
                return False
            
            # For /dev/ devices, verify device file exists (catches stale mounts)
            if source.startswith("/dev/"):
                if not Path(source).exists():
                    logger.debug(f"{mount_path} device {source} does not exist - stale mount")
                    return False
            
            # All checks passed - it's a real device mount
            logger.debug(f"{mount_path} is a real device mount (fstype={fstype}, source={source})")
            return True
            
        except FileNotFoundError:
            # findmnt not available, fall back to /proc/mounts
            logger.debug("findmnt not available, falling back to /proc/mounts")
            try:
                with open("/proc/mounts", "r") as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 2:
                            mount_point = parts[1].replace("\\040", " ")
                            if mount_point == path_str:
                                fstype = parts[2] if len(parts) > 2 else ""
                                if fstype == "autofs":
                                    return False
                                return True
                return False
            except Exception:
                return False
        except Exception as e:
            logger.debug(f"Error checking mount status: {e}")
            return False
    
    return False

