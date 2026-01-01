from __future__ import annotations

from pathlib import Path


def _candidate_names_match(name: str, *, label: str) -> bool:
    # Accept exact match or "label 1" suffix.
    return name == label or name.startswith(label + " ")


def find_candidate_volumes(volumes_root: Path, *, label: str) -> list[Path]:
    """
    macOS quirk: a volume named 'auto-import' may mount as 'auto-import 1', etc.
    We accept any directory starting with the label.
    """
    if not volumes_root.exists():
        return []

    candidates: list[Path] = []
    for p in sorted(volumes_root.iterdir()):
        if not p.is_dir():
            continue
        if _candidate_names_match(p.name, label=label):
            candidates.append(p)
    return candidates


def pick_volume_with_dcim(volumes_root: Path, *, label: str) -> Path | None:
    for vol in find_candidate_volumes(volumes_root, label=label):
        if (vol / "DCIM").is_dir():
            return vol
    return None


def find_candidate_mounts(mount_roots: list[Path], *, label: str) -> list[Path]:
    candidates: list[Path] = []
    for root in mount_roots:
        if not root.exists() or not root.is_dir():
            continue
        # Linux commonly mounts as /media/<user>/<label> (two-level).
        # macOS commonly mounts as /Volumes/<label> (one-level).
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            if _candidate_names_match(p.name, label=label):
                candidates.append(p)
                continue
            # one level deeper
            try:
                for q in sorted(p.iterdir()):
                    if q.is_dir() and _candidate_names_match(q.name, label=label):
                        candidates.append(q)
            except PermissionError:
                continue
    return candidates


def pick_mount_with_dcim(mount_roots: list[Path], *, label: str) -> Path | None:
    for vol in find_candidate_mounts(mount_roots, label=label):
        if (vol / "DCIM").is_dir():
            return vol
    return None


