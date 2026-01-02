from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _candidate_names_match(name: str, *, label: str) -> bool:
    # Accept exact match or "label 1" suffix.
    return name == label or name.startswith(label + " ")


def _is_mount_accessible(where: Path) -> bool:
    """
    Check if a mountpoint is actually accessible by trying to read from the filesystem.
    This is more reliable than just checking if the directory exists - it verifies
    the filesystem is actually readable, not just a stale mount point.
    
    Strategy:
    1. Verify it's a directory
    2. Try to list directory contents (this will fail if device is gone)
    3. If we can list, try to read a file if available (bonus check)
    4. If no files, try to access a subdirectory
    5. If all else fails but we can list, consider it accessible (might be empty card)
    """
    try:
        # First, basic check - is it a directory?
        stat_result = where.stat()
        import stat
        if not stat.S_ISDIR(stat_result.st_mode):
            logger.debug(f"Mount check failed for {where}: not a directory")
            return False
        
        # Try to actually read from the filesystem by listing directory
        # This will fail if the device is gone (stale mount)
        try:
            items = list(where.iterdir())
            logger.debug(f"Mount check: {where} has {len(items)} items")
        except (OSError, IOError, PermissionError) as e:
            logger.debug(f"Mount check failed for {where}: cannot list directory: {e}")
            return False
        
        # If we can list the directory, the mount is likely real
        # But let's try to verify by reading a file if available (more definitive)
        # Look for any file in the root and try to read it
        for item in items:
            if item.is_file():
                # Try to read just the first byte to verify we can access the filesystem
                try:
                    with item.open("rb") as f:
                        f.read(1)  # Read just 1 byte to verify we can access the filesystem
                    logger.debug(f"Mount check passed for {where}: successfully read file {item.name}")
                    return True  # Successfully read from filesystem - mount is definitely real
                except (OSError, IOError) as e:
                    # File exists but can't read - might be stale mount, but listing worked so be lenient
                    logger.debug(f"Mount check: cannot read file {item.name} but listing worked: {e}")
                    # Don't fail here - listing worked, so mount might still be real
        
        # No files found in root, but directory is accessible - that's OK
        # Try accessing a subdirectory if available
        for item in items:
            if item.is_dir():
                try:
                    # Try to list a subdirectory to verify filesystem access
                    list(item.iterdir())
                    logger.debug(f"Mount check passed for {where}: successfully accessed subdirectory {item.name}")
                    return True
                except (OSError, IOError) as e:
                    logger.debug(f"Mount check: cannot access subdirectory {item.name}: {e}")
                    continue
        
        # Directory exists and we can list it - that's good enough
        # Even if empty or we can't read files, if listing works the mount is likely real
        logger.debug(f"Mount check passed for {where}: directory accessible (can list, even if empty)")
        return True
    except (OSError, IOError, PermissionError) as e:
        logger.debug(f"Mount check failed for {where}: exception: {e}")
        return False


def find_candidate_volumes(volumes_root: Path, *, label: str) -> list[Path]:
    """
    macOS quirk: a volume named 'auto-import' may mount as 'auto-import 1', etc.
    We accept any directory starting with the label.
    """
    if not volumes_root.exists():
        return []

    candidates: list[Path] = []
    try:
        for p in sorted(volumes_root.iterdir()):
            try:
                if not p.is_dir():
                    continue
                if _candidate_names_match(p.name, label=label):
                    # Check if mount is actually accessible (filters out stale mounts)
                    if _is_mount_accessible(p):
                        candidates.append(p)
            except (OSError, IOError):
                # Directory became inaccessible, skip it
                continue
    except (OSError, IOError):
        # Volume root became inaccessible
        pass
    return candidates


def pick_volume_with_dcim(volumes_root: Path, *, label: str) -> Path | None:
    for vol in find_candidate_volumes(volumes_root, label=label):
        try:
            dcim_path = vol / "DCIM"
            if dcim_path.is_dir():
                # Try to actually access the DCIM directory - this will fail if it's a stale mount
                try:
                    # Try to list the directory - this will fail if device is gone
                    list(dcim_path.iterdir())
                    return vol
                except (OSError, IOError):
                    # DCIM directory exists but is not accessible - stale mount, skip it
                    continue
        except (OSError, IOError):
            # Volume became inaccessible, skip it
            continue
    return None


def find_candidate_mounts(mount_roots: list[Path], *, label: str) -> list[Path]:
    candidates: list[Path] = []
    for root in mount_roots:
        if not root.exists() or not root.is_dir():
            continue
        # Linux commonly mounts as /media/<user>/<label> (two-level).
        # macOS commonly mounts as /Volumes/<label> (one-level).
        try:
            for p in sorted(root.iterdir()):
                try:
                    if not p.is_dir():
                        continue
                    if _candidate_names_match(p.name, label=label):
                        # Check if mount is actually accessible (filters out stale mounts)
                        if _is_mount_accessible(p):
                            candidates.append(p)
                        continue
                    # one level deeper
                    try:
                        for q in sorted(p.iterdir()):
                            try:
                                if q.is_dir() and _candidate_names_match(q.name, label=label):
                                    # Check if mount is actually accessible (filters out stale mounts)
                                    if _is_mount_accessible(q):
                                        candidates.append(q)
                            except (OSError, IOError):
                                # Directory became inaccessible, skip it
                                continue
                    except (OSError, IOError, PermissionError):
                        continue
                except (OSError, IOError):
                    # Directory became inaccessible, skip it
                    continue
        except (OSError, IOError):
            # Mount root became inaccessible
            continue
    return candidates


def pick_mount_with_dcim(mount_roots: list[Path], *, label: str) -> Path | None:
    """
    Find a mounted volume with the given label that has a DCIM directory.
    Returns the first accessible volume with DCIM, even if DCIM appears empty
    (empty DCIM might be due to filesystem corruption, but we should still try to process it).
    """
    logger.debug(f"Looking for mount with label '{label}' in roots: {mount_roots}")
    candidates = find_candidate_mounts(mount_roots, label=label)
    logger.debug(f"Found {len(candidates)} candidate mounts: {[str(c) for c in candidates]}")
    
    for vol in candidates:
        try:
            dcim_path = vol / "DCIM"
            logger.debug(f"Checking {vol} for DCIM directory: {dcim_path}")
            if dcim_path.is_dir():
                logger.debug(f"DCIM directory exists at {dcim_path}")
                # Try to actually access the DCIM directory - this will fail if it's a stale mount
                try:
                    # Try to list the directory - this will fail if device is gone
                    # Don't check if empty - even empty DCIM should be processed (might have filesystem issues)
                    dcim_items = list(dcim_path.iterdir())
                    logger.debug(f"DCIM directory accessible at {dcim_path} with {len(dcim_items)} items")
                    return vol
                except (OSError, IOError) as e:
                    # DCIM directory exists but is not accessible - stale mount, skip it
                    logger.debug(f"DCIM directory exists but not accessible at {dcim_path}: {e}")
                    continue
            else:
                logger.debug(f"No DCIM directory at {dcim_path}")
        except (OSError, IOError) as e:
            # Volume became inaccessible, skip it
            logger.debug(f"Volume {vol} became inaccessible: {e}")
            continue
    
    logger.debug(f"No accessible mount with DCIM found for label '{label}'")
    return None


