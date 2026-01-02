from __future__ import annotations

from pathlib import Path


def _candidate_names_match(name: str, *, label: str) -> bool:
    # Accept exact match or "label 1" suffix.
    return name == label or name.startswith(label + " ")


def _is_mount_accessible(where: Path) -> bool:
    """
    Check if a mountpoint is actually accessible (not just in mount table).
    This catches cases where the mount is "lazy unmounted" - still exists as a directory
    but the device is actually gone.
    
    Uses a lightweight check that will fail if the underlying device is removed.
    """
    try:
        # Try to stat the mountpoint itself (not its contents, to avoid triggering automount)
        # If the mount is stale, this will fail with ENODEV or EIO
        stat_result = where.stat()
        # Check if it's actually a directory (mountpoints should be directories)
        import stat
        if not stat.S_ISDIR(stat_result.st_mode):
            return False
        
        # Try to access the directory in a way that will fail if device is gone
        # We use a very lightweight check: try to get one directory entry
        # This will raise OSError with ENODEV/EIO if the device is gone
        try:
            # Use next() on iterator - very lightweight, doesn't read all entries
            next(where.iterdir(), None)
        except (OSError, IOError, PermissionError):
            # OSError/IOError with ENODEV/EIO means device is gone
            # PermissionError might be fine, but let's be conservative and assume it's gone
            return False
        except StopIteration:
            # Empty directory is fine
            pass
        
        return True
    except (OSError, IOError, PermissionError):
        # Can't stat or access - mount is likely gone
        # Common errors: ENODEV (No such device), EIO (Input/output error)
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
            if (vol / "DCIM").is_dir():
                return vol
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
    for vol in find_candidate_mounts(mount_roots, label=label):
        try:
            if (vol / "DCIM").is_dir():
                return vol
        except (OSError, IOError):
            # Volume became inaccessible, skip it
            continue
    return None


