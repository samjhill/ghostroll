from __future__ import annotations

import logging
import os
import platform
import subprocess
from pathlib import Path

from .mount_check import is_real_device_mount

# Use the main ghostroll logger so our messages are visible
logger = logging.getLogger("ghostroll.volume_watch")


def _candidate_names_match(name: str, *, label: str) -> bool:
    """
    Check if a volume name matches the target label.
    Handles macOS quirk where 'auto-import' may mount as 'auto-import 1', etc.
    """
    return name == label or name.startswith(label + " ")


def _is_actually_mounted(volume_path: Path) -> bool:
    """
    Check if a path is actually a mount point (not just a regular directory or automount).
    
    Uses findmnt on Linux (simpler and more reliable than parsing /proc/mounts).
    On macOS, uses mount command.
    
    Returns True only if it's a real device mount (not autofs).
    """
    system = platform.system().lower()
    vol_str = str(volume_path)
    
    # On macOS, anything in /Volumes is always a mount
    if system == "darwin":
        if vol_str.startswith("/Volumes/"):
            return True
        # For other paths, check mount command
        try:
            result = subprocess.run(
                ["mount"], capture_output=True, text=True, timeout=2
            )
            return vol_str in result.stdout
        except Exception:
            return False
    
    # On Linux, use findmnt - much simpler and more reliable
    if system == "linux":
        # /media and /run/media are typically always mounts (trust them)
        if vol_str.startswith("/media/") or vol_str.startswith("/run/media/"):
            return True
        
        # For /mnt and other paths, use findmnt to check
        try:
            # findmnt -n -o FSTYPE,SOURCE <path> returns filesystem type and source device
            # Returns nothing if not mounted, or "autofs" if it's an automount placeholder
            result = subprocess.run(
                ["findmnt", "-n", "-o", "FSTYPE,SOURCE", vol_str],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode != 0:
                # Not mounted at all
                logger.debug(f"Volume {vol_str} is not mounted (findmnt returned {result.returncode})")
                return False
            
            output = result.stdout.strip()
            if not output:
                # Empty output means not mounted
                logger.debug(f"Volume {vol_str} is not mounted (findmnt returned empty)")
                return False
            
            # Parse output: "FSTYPE SOURCE" (e.g., "vfat /dev/sdb1" or "autofs systemd-1")
            parts = output.split(None, 1)
            if len(parts) < 1:
                return False
            
            fstype = parts[0]
            source = parts[1] if len(parts) > 1 else ""
            
            # Reject autofs (automount placeholder)
            if fstype == "autofs":
                logger.debug(f"Volume {vol_str} is autofs - rejecting as automount placeholder")
                return False
            
            # Reject systemd-1 or autofs sources
            if source.startswith("systemd-1") or "autofs" in source.lower():
                logger.debug(f"Volume {vol_str} has automount source {source} - rejecting")
                return False
            
            # For /dev/ devices, verify the device file exists (catch stale mounts)
            if source.startswith("/dev/"):
                if not Path(source).exists():
                    logger.debug(f"Volume {vol_str} device {source} does not exist - rejecting as stale mount")
                    return False
            
            # It's a real mount with a real filesystem
            logger.debug(f"Volume {vol_str} is a real mount (fstype={fstype}, source={source})")
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
                            if mount_point == vol_str:
                                fstype = parts[2] if len(parts) > 2 else ""
                                if fstype == "autofs":
                                    return False
                                return True
                return False
            except Exception:
                return False
        except Exception as e:
            logger.debug(f"Error checking mount status with findmnt: {e}")
            return False
    
    return False


def _is_volume_accessible(volume_path: Path) -> bool:
    """
    Verify that a volume path is actually accessible (not a stale mount or regular directory).
    
    Strategy:
    1. Check it exists and is a directory
    2. For /mnt paths: try to access directory (triggers automount), wait, then check mount status
    3. Try to list its contents (will fail if device is gone)
    
    The key is to trigger automount by accessing the directory BEFORE checking mount status.
    """
    try:
        # Basic check: exists and is a directory
        if not volume_path.exists():
            logger.debug(f"Volume {volume_path} does not exist")
            return False
        
        if not volume_path.is_dir():
            logger.debug(f"Volume {volume_path} is not a directory")
            return False
        
        vol_str = str(volume_path)
        
        # For /mnt paths, we MUST verify it's actually mounted (not just a directory or autofs)
        # Standard mount locations (/Volumes, /media, /run/media) are assumed to be mounts
        if vol_str.startswith("/mnt/"):
            # Use the bulletproof mount check - it handles automount triggering and verification
            if is_real_device_mount(volume_path, trigger_automount=True):
                logger.debug(f"✓ {volume_path} is a real device mount")
                # Verify we can actually read files (catches edge cases)
                try:
                    list(volume_path.iterdir())
                    return True
                except (OSError, IOError):
                    logger.debug(f"{volume_path} is mounted but not accessible")
                    return False
            else:
                logger.debug(f"Rejecting {volume_path}: not a real device mount")
                return False
        
        # Try to list directory contents - this will fail if device is gone or not accessible
        try:
            items = list(volume_path.iterdir())
            logger.debug(f"Volume {volume_path} is accessible (has {len(items)} items)")
            return True
        except (OSError, IOError) as e:
            logger.debug(f"Volume {volume_path} exists but cannot list contents: {e}")
            return False
            
    except Exception as e:
        logger.debug(f"Error checking volume {volume_path}: {e}")
        return False


def find_candidate_mounts(mount_roots: list[Path], *, label: str, verbose: bool = False) -> list[Path]:
    """
    Find all mounted volumes that match the given label.
    
    Searches in mount_roots (e.g., [/Volumes, /media, /mnt]) and checks
    both one-level (macOS: /Volumes/auto-import) and two-level (Linux: /media/user/auto-import).
    
    Args:
        mount_roots: List of mount root directories to search
        label: Volume label to match
        verbose: If True, log at INFO level. If False, log at DEBUG level.
    
    Returns list of accessible volume paths that match the label.
    """
    candidates = []
    
    log_level = logger.info if verbose else logger.debug
    log_level(f"Searching for volume with label '{label}' in: {[str(r) for r in mount_roots]}")
    
    for mount_root in mount_roots:
        if not mount_root.exists():
            logger.debug(f"Mount root {mount_root} does not exist, skipping")
            continue
        
        if not mount_root.is_dir():
            logger.debug(f"Mount root {mount_root} is not a directory, skipping")
            continue
        
        try:
            # Check one level deep (macOS style: /Volumes/auto-import)
            for item in mount_root.iterdir():
                try:
                    if not item.is_dir():
                        continue
                    
                    if _candidate_names_match(item.name, label=label):
                        logger.debug(f"Found candidate volume: {item}")
                        if _is_volume_accessible(item):
                            logger.info(f"  ✓ Volume is accessible: {item}")
                            candidates.append(item)
                        else:
                            # Only log at debug level for rejected volumes to reduce noise
                            logger.debug(f"  ✗ Volume exists but is not accessible: {item}")
                        continue
                    
                    # Check two levels deep (Linux style: /media/user/auto-import)
                    try:
                        for subitem in item.iterdir():
                            try:
                                if not subitem.is_dir():
                                    continue
                                
                                if _candidate_names_match(subitem.name, label=label):
                                    logger.debug(f"Found candidate volume: {subitem}")
                                    if _is_volume_accessible(subitem):
                                        logger.info(f"  ✓ Volume is accessible: {subitem}")
                                        candidates.append(subitem)
                                    else:
                                        # Only log at debug level for rejected volumes to reduce noise
                                        logger.debug(f"  ✗ Volume exists but is not accessible: {subitem}")
                            except (OSError, IOError):
                                continue
                    except (OSError, IOError, PermissionError):
                        continue
                        
                except (OSError, IOError):
                    continue
                    
        except (OSError, IOError) as e:
            logger.debug(f"Error scanning mount root {mount_root}: {e}")
            continue
    
    if candidates:
        logger.info(f"Found {len(candidates)} accessible candidate volume(s): {[str(c) for c in candidates]}")
    else:
        log_level = logger.info if verbose else logger.debug
        log_level(f"Found {len(candidates)} accessible candidate volume(s): []")
    return candidates


def pick_mount_with_dcim(mount_roots: list[Path], *, label: str, verbose: bool = True) -> Path | None:
    """
    Find a mounted volume with the given label that has an accessible DCIM directory.
    
    This is the main function used by the watch command to detect camera SD cards.
    
    Args:
        mount_roots: List of mount root directories to search
        label: Volume label to match
        verbose: If True, log at INFO level. If False, log at DEBUG level.
    
    Returns the first accessible volume with DCIM, or None if not found.
    """
    log_level = logger.info if verbose else logger.debug
    log_level(f"Looking for volume '{label}' with DCIM directory...")
    
    candidates = find_candidate_mounts(mount_roots, label=label, verbose=verbose)
    
    if not candidates:
        log_level = logger.info if verbose else logger.debug
        log_level(f"No volumes found with label '{label}'")
        return None
    
    # Check each candidate for DCIM directory
    for vol in candidates:
        dcim_path = vol / "DCIM"
        log_level(f"Checking {vol} for DCIM directory at {dcim_path}")
        
        try:
            if not dcim_path.exists():
                logger.debug(f"  DCIM directory does not exist at {dcim_path}")
                continue
            
            if not dcim_path.is_dir():
                logger.debug(f"  DCIM path exists but is not a directory: {dcim_path}")
                continue
            
            # Try to access the DCIM directory to verify it's not a stale mount
            try:
                dcim_items = list(dcim_path.iterdir())
                log_level(f"  ✓ DCIM directory is accessible with {len(dcim_items)} items")
                log_level(f"Found valid camera volume: {vol}")
                return vol
            except (OSError, IOError) as e:
                # Only warn if verbose, otherwise debug
                if verbose:
                    logger.warning(f"  ✗ DCIM directory exists but is not accessible: {e}")
                else:
                    logger.debug(f"  ✗ DCIM directory exists but is not accessible: {e}")
                continue
                
        except Exception as e:
            logger.debug(f"  Error checking DCIM directory: {e}")
            continue
    
    # Only warn if verbose, otherwise use the log_level
    if verbose:
        logger.warning(f"Found {len(candidates)} volume(s) with label '{label}' but none have accessible DCIM directory")
    else:
        log_level(f"Found {len(candidates)} volume(s) with label '{label}' but none have accessible DCIM directory")
    return None


# Legacy macOS-specific functions for backwards compatibility
def find_candidate_volumes(volumes_root: Path, *, label: str) -> list[Path]:
    """
    macOS-specific: Find all mounted volumes under volumes_root that match the label.
    
    This is a legacy function kept for backwards compatibility.
    For new code, use find_candidate_mounts with a list of mount roots.
    """
    return find_candidate_mounts([volumes_root], label=label)


def pick_volume_with_dcim(volumes_root: Path, *, label: str) -> Path | None:
    """
    macOS-specific: Find a mounted volume with DCIM directory.
    
    This is a legacy function kept for backwards compatibility.
    For new code, use pick_mount_with_dcim with a list of mount roots.
    """
    return pick_mount_with_dcim([volumes_root], label=label)
