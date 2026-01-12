from __future__ import annotations

import logging
from pathlib import Path

import pytest
from PIL import Image

from ghostroll.config import load_config
from ghostroll.pipeline import resume_incomplete_sessions


def _make_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (800, 600), (12, 34, 56))
    img.save(path, format="JPEG", quality=85)


def test_resume_incomplete_sessions_calls_finalize(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Minimal config rooted in tmpdir
    base = tmp_path / "ghostroll"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(base))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(base / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_STATUS_PATH", str(base / "status.json"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_PATH", str(base / "status.png"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_SIZE", "320x240")
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "photo-ingest-project")
    monkeypatch.setenv("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")

    cfg = load_config()

    # Create a fake session with local originals
    session_id = "shoot-2026-01-12_214933_197438"
    session_dir = cfg.sessions_dir / session_id
    _make_jpeg(session_dir / "originals" / "DCIM" / "100CANON" / "IMG_0001.JPG")

    # Pretend S3 status.json exists and is still uploading
    monkeypatch.setattr("ghostroll.pipeline.s3_object_exists", lambda **kwargs: True)
    monkeypatch.setattr("ghostroll.pipeline.s3_get_json", lambda **kwargs: {"uploading": True})

    called: list[str] = []

    def finalize_stub(*, cfg, session_id: str, session_dir: Path, logger, status=None) -> None:
        called.append(session_id)

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    resumed = resume_incomplete_sessions(cfg=cfg, logger=logger, status=None, max_sessions=3, finalize_fn=finalize_stub)
    assert resumed == 1
    assert called == [session_id]


def test_resume_incomplete_sessions_skips_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "ghostroll"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(base))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(base / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_STATUS_PATH", str(base / "status.json"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_PATH", str(base / "status.png"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_SIZE", "320x240")
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "photo-ingest-project")
    monkeypatch.setenv("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")

    cfg = load_config()

    session_id = "shoot-2026-01-12_214933_197438"
    session_dir = cfg.sessions_dir / session_id
    _make_jpeg(session_dir / "originals" / "DCIM" / "100CANON" / "IMG_0001.JPG")

    monkeypatch.setattr("ghostroll.pipeline.s3_object_exists", lambda **kwargs: True)
    monkeypatch.setattr("ghostroll.pipeline.s3_get_json", lambda **kwargs: {"uploading": False})

    logger = logging.getLogger("test")
    logger.addHandler(logging.NullHandler())

    resumed = resume_incomplete_sessions(cfg=cfg, logger=logger, status=None, max_sessions=3, finalize_fn=lambda **_: None)
    assert resumed == 0

