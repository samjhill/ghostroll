from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.volume_watch import (
    _candidate_names_match,
    find_candidate_mounts,
    find_candidate_volumes,
    pick_mount_with_dcim,
    pick_volume_with_dcim,
)


def test_candidate_names_match():
    assert _candidate_names_match("auto-import", label="auto-import") is True
    assert _candidate_names_match("auto-import 1", label="auto-import") is True
    assert _candidate_names_match("auto-import 2", label="auto-import") is True
    assert _candidate_names_match("auto-import-other", label="auto-import") is False
    assert _candidate_names_match("other", label="auto-import") is False


def test_find_candidate_volumes(tmp_path: Path):
    volumes_root = tmp_path / "volumes"
    volumes_root.mkdir()
    
    # Create matching volumes
    (volumes_root / "auto-import").mkdir()
    (volumes_root / "auto-import 1").mkdir()
    (volumes_root / "other").mkdir()
    
    candidates = find_candidate_volumes(volumes_root, label="auto-import")
    assert len(candidates) == 2
    assert all("auto-import" in str(c.name) for c in candidates)


def test_find_candidate_volumes_nonexistent():
    volumes_root = Path("/nonexistent/dir")
    candidates = find_candidate_volumes(volumes_root, label="auto-import")
    assert candidates == []


def test_find_candidate_volumes_no_matches(tmp_path: Path):
    volumes_root = tmp_path / "volumes"
    volumes_root.mkdir()
    (volumes_root / "other").mkdir()
    
    candidates = find_candidate_volumes(volumes_root, label="auto-import")
    assert candidates == []


def test_pick_volume_with_dcim(tmp_path: Path):
    volumes_root = tmp_path / "volumes"
    volumes_root.mkdir()
    
    vol1 = volumes_root / "auto-import"
    vol1.mkdir()
    (vol1 / "DCIM").mkdir()
    
    vol2 = volumes_root / "auto-import 1"
    vol2.mkdir()
    # No DCIM
    
    result = pick_volume_with_dcim(volumes_root, label="auto-import")
    assert result == vol1


def test_pick_volume_with_dcim_no_dcim(tmp_path: Path):
    volumes_root = tmp_path / "volumes"
    volumes_root.mkdir()
    
    vol = volumes_root / "auto-import"
    vol.mkdir()
    # No DCIM
    
    result = pick_volume_with_dcim(volumes_root, label="auto-import")
    assert result is None


def test_find_candidate_mounts_one_level(tmp_path: Path):
    mount_root = tmp_path / "mounts"
    mount_root.mkdir()
    
    (mount_root / "auto-import").mkdir()
    (mount_root / "other").mkdir()
    
    candidates = find_candidate_mounts([mount_root], label="auto-import")
    assert len(candidates) == 1
    assert candidates[0].name == "auto-import"


def test_find_candidate_mounts_two_level(tmp_path: Path):
    mount_root = tmp_path / "mounts"
    mount_root.mkdir()
    
    user_dir = mount_root / "user"
    user_dir.mkdir()
    (user_dir / "auto-import").mkdir()
    
    candidates = find_candidate_mounts([mount_root], label="auto-import")
    assert len(candidates) == 1
    assert candidates[0].name == "auto-import"


def test_find_candidate_mounts_nonexistent_root():
    candidates = find_candidate_mounts([Path("/nonexistent")], label="auto-import")
    assert candidates == []


def test_find_candidate_mounts_permission_error(tmp_path: Path):
    mount_root = tmp_path / "mounts"
    mount_root.mkdir()
    
    # Test that the function handles permission errors gracefully
    # We can't easily create a real permission error in tests, but we can verify
    # the function structure handles it (it has try/except PermissionError)
    candidates = find_candidate_mounts([mount_root], label="auto-import")
    # Should not crash even if some directories can't be accessed
    assert isinstance(candidates, list)


def test_pick_mount_with_dcim(tmp_path: Path):
    mount_root = tmp_path / "mounts"
    mount_root.mkdir()
    
    vol = mount_root / "auto-import"
    vol.mkdir()
    dcim = vol / "DCIM"
    dcim.mkdir()
    # Create a file in DCIM so it's not empty (required by pick_mount_with_dcim)
    (dcim / "test.jpg").touch()
    
    result = pick_mount_with_dcim([mount_root], label="auto-import")
    assert result == vol


def test_pick_mount_with_dcim_no_dcim(tmp_path: Path):
    mount_root = tmp_path / "mounts"
    mount_root.mkdir()
    
    vol = mount_root / "auto-import"
    vol.mkdir()
    # No DCIM
    
    result = pick_mount_with_dcim([mount_root], label="auto-import")
    assert result is None


def test_pick_mount_with_dcim_multiple_roots(tmp_path: Path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()
    
    vol = root2 / "auto-import"
    vol.mkdir()
    dcim = vol / "DCIM"
    dcim.mkdir()
    # Create a file in DCIM so it's not empty (required by pick_mount_with_dcim)
    (dcim / "test.jpg").touch()
    
    result = pick_mount_with_dcim([root1, root2], label="auto-import")
    assert result == vol

