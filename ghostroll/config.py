from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


@dataclass(frozen=True)
class Config:
    sd_label: str
    base_output_dir: Path
    db_path: Path

    s3_bucket: str
    s3_prefix_root: str
    presign_expiry_seconds: int

    share_max_long_edge: int
    share_quality: int
    thumb_max_long_edge: int
    thumb_quality: int

    poll_seconds: float

    @property
    def sessions_dir(self) -> Path:
        return self.base_output_dir

    @property
    def volumes_root(self) -> Path:
        return Path("/Volumes")


def load_config(
    *,
    sd_label: str | None = None,
    base_output_dir: str | None = None,
    db_path: str | None = None,
    s3_bucket: str | None = None,
    s3_prefix_root: str | None = None,
    presign_expiry_seconds: int | None = None,
    share_max_long_edge: int | None = None,
    share_quality: int | None = None,
    thumb_max_long_edge: int | None = None,
    thumb_quality: int | None = None,
    poll_seconds: float | None = None,
) -> Config:
    env = os.environ

    sd_label = sd_label or env.get("GHOSTROLL_SD_LABEL", "auto-import")
    base_output_dir = base_output_dir or env.get("GHOSTROLL_BASE_DIR", "~/ghostroll")
    db_path = db_path or env.get("GHOSTROLL_DB_PATH", "~/.ghostroll/ghostroll.db")

    s3_bucket = s3_bucket or env.get("GHOSTROLL_S3_BUCKET", "photo-ingest-project")
    s3_prefix_root = s3_prefix_root or env.get("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")
    presign_expiry_seconds = int(
        presign_expiry_seconds
        if presign_expiry_seconds is not None
        else env.get("GHOSTROLL_PRESIGN_EXPIRY_SECONDS", "604800")
    )

    share_max_long_edge = int(
        share_max_long_edge
        if share_max_long_edge is not None
        else env.get("GHOSTROLL_SHARE_MAX_LONG_EDGE", "2048")
    )
    share_quality = int(
        share_quality if share_quality is not None else env.get("GHOSTROLL_SHARE_QUALITY", "90")
    )
    thumb_max_long_edge = int(
        thumb_max_long_edge
        if thumb_max_long_edge is not None
        else env.get("GHOSTROLL_THUMB_MAX_LONG_EDGE", "512")
    )
    thumb_quality = int(
        thumb_quality if thumb_quality is not None else env.get("GHOSTROLL_THUMB_QUALITY", "85")
    )

    poll_seconds = float(
        poll_seconds if poll_seconds is not None else env.get("GHOSTROLL_POLL_SECONDS", "2")
    )

    cfg = Config(
        sd_label=sd_label,
        base_output_dir=_expand(base_output_dir),
        db_path=_expand(db_path),
        s3_bucket=s3_bucket,
        s3_prefix_root=s3_prefix_root if s3_prefix_root.endswith("/") else (s3_prefix_root + "/"),
        presign_expiry_seconds=presign_expiry_seconds,
        share_max_long_edge=share_max_long_edge,
        share_quality=share_quality,
        thumb_max_long_edge=thumb_max_long_edge,
        thumb_quality=thumb_quality,
        poll_seconds=poll_seconds,
    )

    cfg.base_output_dir.mkdir(parents=True, exist_ok=True)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    return cfg


