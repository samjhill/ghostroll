from __future__ import annotations

import os
from pathlib import Path


def _candidate_names_match(name: str, *, label: str) -> bool:
    # Accept exact match or "label 1" suffix.
    return name == label or name.startswith(label + " ")


def _is_mount_accessible(where: Path) -> bool:
    """
    Simple check if a mountpoint is accessible.
    Just verify we can stat it and it's a directory.
    """
    try:
        stat_result = where.stat()
        import stat
        return stat.S_ISDIR(stat_result.st_mode)
    except (OSError, IOError, PermissionError):
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
    for vol in find_candidate_mounts(mount_roots, label=label):
        try:
            dcim_path = vol / "DCIM"
            if dcim_path.is_dir():
                # Try to actually access the DCIM directory - this will fail if it's a stale mount
                try:
                    # Try to list the directory - this will fail if device is gone
                    # Don't check if empty - even empty DCIM should be processed (might have filesystem issues)
                    list(dcim_path.iterdir())
                    return vol
                except (OSError, IOError):
                    # DCIM directory exists but is not accessible - stale mount, skip it
                    continue
        except (OSError, IOError):
            # Volume became inaccessible, skip it
            continue
    return None


