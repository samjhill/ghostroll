from __future__ import annotations

from pathlib import Path


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
        if p.name == label or p.name.startswith(label + " "):
            candidates.append(p)
    return candidates


def pick_volume_with_dcim(volumes_root: Path, *, label: str) -> Path | None:
    for vol in find_candidate_volumes(volumes_root, label=label):
        if (vol / "DCIM").is_dir():
            return vol
    return None


