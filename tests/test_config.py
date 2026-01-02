from __future__ import annotations

import os
from pathlib import Path

import pytest

from ghostroll.config import Config, load_config, _parse_size, _split_paths


def test_parse_size():
    assert _parse_size("800x480") == (800, 480)
    assert _parse_size("1920x1080") == (1920, 1080)
    assert _parse_size("100x200") == (100, 200)

    with pytest.raises(ValueError, match="Invalid size"):
        _parse_size("800")
    with pytest.raises(ValueError, match="Invalid size"):
        _parse_size("invalid")


def test_split_paths():
    paths = _split_paths("/Volumes,/media,/run/media")
    assert len(paths) == 3
    assert all(isinstance(p, Path) for p in paths)

    paths = _split_paths("/Volumes, /media , /run/media ")
    assert len(paths) == 3

    paths = _split_paths("")
    assert len(paths) == 0

    paths = _split_paths("/single/path")
    assert len(paths) == 1


def test_load_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GHOSTROLL_SD_LABEL", raising=False)
    monkeypatch.delenv("GHOSTROLL_BASE_DIR", raising=False)
    monkeypatch.delenv("GHOSTROLL_DB_PATH", raising=False)

    cfg = load_config()
    assert cfg.sd_label == "auto-import"
    assert "ghostroll" in str(cfg.base_output_dir).lower()
    assert "ghostroll.db" in str(cfg.db_path)


def test_load_config_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_SD_LABEL", "test-label")
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path / "custom"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("GHOSTROLL_SHARE_MAX_LONG_EDGE", "4096")
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_SIZE", "1024x768")

    cfg = load_config()
    assert cfg.sd_label == "test-label"
    assert cfg.base_output_dir == tmp_path / "custom"
    assert cfg.s3_bucket == "test-bucket"
    assert cfg.share_max_long_edge == 4096
    assert cfg.status_image_size == (1024, 768)


def test_load_config_arg_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_SD_LABEL", "env-label")
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "env-bucket")

    cfg = load_config(sd_label="arg-label", s3_bucket="arg-bucket")
    assert cfg.sd_label == "arg-label"
    assert cfg.s3_bucket == "arg-bucket"


def test_load_config_mount_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_MOUNT_ROOTS", "/custom1,/custom2")
    cfg = load_config()
    assert len(cfg.mount_roots) == 2
    assert any("/custom1" in str(p) for p in cfg.mount_roots)
    assert any("/custom2" in str(p) for p in cfg.mount_roots)

    monkeypatch.delenv("GHOSTROLL_MOUNT_ROOTS", raising=False)
    cfg = load_config()
    assert len(cfg.mount_roots) >= 4  # Default includes /Volumes, /media, etc.


def test_load_config_s3_prefix_normalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_S3_PREFIX_ROOT", "sessions")
    cfg = load_config()
    assert cfg.s3_prefix_root.endswith("/")

    monkeypatch.setenv("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")
    cfg = load_config()
    assert cfg.s3_prefix_root.endswith("/")


def test_config_properties():
    cfg = load_config()
    assert cfg.sessions_dir == cfg.base_output_dir
    assert cfg.volumes_root == Path("/Volumes")


def test_config_creates_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base_dir = tmp_path / "ghostroll"
    db_dir = tmp_path / ".ghostroll"
    status_dir = tmp_path / "status"

    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(base_dir))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(db_dir / "db.db"))
    monkeypatch.setenv("GHOSTROLL_STATUS_PATH", str(status_dir / "status.json"))

    cfg = load_config()
    assert base_dir.exists()
    assert db_dir.exists()
    assert status_dir.exists()

