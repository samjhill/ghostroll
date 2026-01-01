from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import media
from .aws_cli import AwsCliError, s3_cp, s3_presign
from .config import Config
from .db import connect
from .gallery import build_index_html, build_index_html_presigned
from .hashing import sha256_file
from .image_processing import render_jpeg_derivative
from .logging_utils import attach_session_logfile


class PipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class SessionPaths:
    session_id: str
    session_dir: Path
    originals_dir: Path
    derived_share_dir: Path
    derived_thumbs_dir: Path
    index_html: Path
    share_txt: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_id_now() -> str:
    # local time for human readability
    # include microseconds to avoid collisions if runs start within the same second
    return "shoot-" + datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")


def _safe_rel_under(root: Path, path: Path) -> Path:
    rel = path.relative_to(root)
    # avoid sneaky paths (shouldn't happen with relative_to, but belt+suspenders)
    if ".." in rel.parts:
        raise PipelineError(f"Refusing to use unsafe relative path: {rel}")
    return rel


def _copy2_ignore_existing(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.copy2(src, dst)
    return True


def _db_has_ingested(conn: sqlite3.Connection, sha256: str) -> bool:
    row = conn.execute("SELECT 1 FROM ingested_files WHERE sha256 = ?", (sha256,)).fetchone()
    return row is not None


def _db_mark_ingested(
    conn: sqlite3.Connection, *, sha256: str, size_bytes: int, source_hint: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO ingested_files(sha256,size_bytes,first_seen_utc,source_hint) "
        "VALUES(?,?,?,?)",
        (sha256, size_bytes, _utc_now(), source_hint),
    )


def _db_uploaded_sha(conn: sqlite3.Connection, *, s3_key: str) -> str | None:
    row = conn.execute(
        "SELECT local_sha256 FROM uploads WHERE s3_key = ?", (s3_key,)
    ).fetchone()
    return row["local_sha256"] if row is not None else None


def _db_mark_uploaded(
    conn: sqlite3.Connection, *, s3_key: str, local_sha256: str, size_bytes: int
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO uploads(s3_key,local_sha256,size_bytes,uploaded_utc) VALUES(?,?,?,?)",
        (s3_key, local_sha256, size_bytes, _utc_now()),
    )


def _iter_media_files(dcim_dir: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(dcim_dir.rglob("*")):
        if p.is_file() and media.is_media(p):
            out.append(p)
    return out


def _pair_prefer_jpeg(files: list[Path]) -> tuple[list[Path], list[Path]]:
    """
    Returns (jpeg_sources_for_derivatives, raw_sources_to_ingest_only).
    If RAW+JPEG exist for same stem in same folder, prefer JPEG for derivatives.
    """
    by_key: dict[tuple[Path, str], list[Path]] = {}
    for p in files:
        by_key.setdefault((p.parent, p.stem.lower()), []).append(p)

    jpegs: list[Path] = []
    raws: list[Path] = []
    for (_parent, _stem), group in by_key.items():
        group_j = [p for p in group if media.is_jpeg(p)]
        group_r = [p for p in group if media.is_raw(p)]
        if group_j:
            jpegs.extend(group_j)
        raws.extend(group_r)
    return sorted(set(jpegs)), sorted(set(raws))


def run_pipeline(
    *,
    cfg: Config,
    volume_path: Path,
    logger,
    always_create_session: bool = False,
    session_id: str | None = None,
) -> tuple[SessionPaths | None, str | None]:
    """
    Returns (session_paths or None if no-op, presigned_url or None).
    """
    dcim_dir = volume_path / "DCIM"
    if not dcim_dir.is_dir():
        raise PipelineError(f"Volume has no DCIM directory: {dcim_dir}")

    conn = connect(cfg.db_path)
    try:
        all_media = _iter_media_files(dcim_dir)
        jpeg_sources, raw_sources = _pair_prefer_jpeg(all_media)
        logger.info(f"Discovered media files: {len(all_media)} (JPEG candidates: {len(jpeg_sources)}, RAW: {len(raw_sources)})")

        # Determine what's new by hashing.
        new_files: list[tuple[Path, str, int]] = []
        skipped = 0
        for p in all_media:
            sha, size = sha256_file(p)
            if _db_has_ingested(conn, sha):
                skipped += 1
                continue
            new_files.append((p, sha, size))

        logger.info(f"New files: {len(new_files)}; skipped already-seen: {skipped}")
        if not new_files and not always_create_session:
            return None, None

        session_id = session_id or _session_id_now()
        session_dir = cfg.sessions_dir / session_id
        originals_dir = session_dir / "originals"
        derived_share_dir = session_dir / "derived" / "share"
        derived_thumbs_dir = session_dir / "derived" / "thumbs"
        index_html = session_dir / "index.html"
        share_txt = session_dir / "share.txt"

        sp = SessionPaths(
            session_id=session_id,
            session_dir=session_dir,
            originals_dir=originals_dir,
            derived_share_dir=derived_share_dir,
            derived_thumbs_dir=derived_thumbs_dir,
            index_html=index_html,
            share_txt=share_txt,
        )

        session_dir.mkdir(parents=True, exist_ok=True)
        attach_session_logfile(logger, session_dir)
        originals_dir.mkdir(parents=True, exist_ok=True)
        derived_share_dir.mkdir(parents=True, exist_ok=True)
        derived_thumbs_dir.mkdir(parents=True, exist_ok=True)

        # Ingest: copy only new files, preserving DCIM structure under originals/DCIM/
        copied = 0
        for src, sha, size in new_files:
            rel = _safe_rel_under(dcim_dir, src)
            dst = originals_dir / "DCIM" / rel
            if _copy2_ignore_existing(src, dst):
                copied += 1
            _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=str(src))
        conn.commit()
        logger.info(f"Ingested originals copied: {copied} -> {originals_dir}")

        # Process: only JPEGs that are newly ingested this run (fast + matches "new since last time" UX).
        new_sha_set = {sha for (_p, sha, _s) in new_files}

        # Map from DCIM source path to sha for quick membership
        src_sha: dict[Path, str] = {p: sha for (p, sha, _s) in new_files}

        # Derived outputs mirror DCIM relpath and normalize to .jpg
        processed = 0
        for src in jpeg_sources:
            sha = src_sha.get(src)
            if sha is None or sha not in new_sha_set:
                continue
            rel = _safe_rel_under(dcim_dir, src).with_suffix(".jpg")
            share_out = derived_share_dir / rel
            thumb_out = derived_thumbs_dir / rel
            if not share_out.exists():
                render_jpeg_derivative(
                    src,
                    dst_path=share_out,
                    max_long_edge=cfg.share_max_long_edge,
                    quality=cfg.share_quality,
                )
            if not thumb_out.exists():
                render_jpeg_derivative(
                    src,
                    dst_path=thumb_out,
                    max_long_edge=cfg.thumb_max_long_edge,
                    quality=cfg.thumb_quality,
                )
            processed += 1
        logger.info(f"Processed JPEGs (share+thumb): {processed}")

        # Gallery
        build_index_html(session_id=session_id, thumbs_dir=derived_thumbs_dir, out_path=index_html)
        logger.info(f"Generated gallery: {index_html}")

        # Upload (retry-tolerant) with per-key upload dedupe (idempotent if re-run)
        prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
        upload_failures: list[str] = []

        def upload_one(local: Path, key: str) -> None:
            sha, size = sha256_file(local)
            prev_sha = _db_uploaded_sha(conn, s3_key=key)
            if prev_sha == sha:
                return
            try:
                s3_cp(local, bucket=cfg.s3_bucket, key=key, retries=3)
                _db_mark_uploaded(conn, s3_key=key, local_sha256=sha, size_bytes=size)
                conn.commit()
            except AwsCliError as e:
                upload_failures.append(f"{local} -> s3://{cfg.s3_bucket}/{key}: {e}")

        # Upload share/thumb trees
        for p in sorted(derived_share_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(derived_share_dir)
            key = f"{prefix}/share/{rel.as_posix()}"
            upload_one(p, key)

        for p in sorted(derived_thumbs_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(derived_thumbs_dir)
            key = f"{prefix}/thumbs/{rel.as_posix()}"
            upload_one(p, key)

        if upload_failures:
            logger.error("Upload failures:\n" + "\n".join(upload_failures))
            raise PipelineError(f"Upload failed for {len(upload_failures)} objects. See log for details.")

        # Build an S3-shareable gallery that embeds presigned URLs for assets (bucket remains private).
        # We keep the local index.html (relative paths) for offline/local browsing.
        presigned_items: list[tuple[str, str]] = []
        for t in sorted([p for p in derived_thumbs_dir.rglob("*") if p.is_file()]):
            rel = t.relative_to(derived_thumbs_dir)
            thumb_key = f"{prefix}/thumbs/{rel.as_posix()}"
            share_key = f"{prefix}/share/{rel.with_suffix('.jpg').as_posix()}"
            thumb_url = s3_presign(
                bucket=cfg.s3_bucket,
                key=thumb_key,
                expires_in_seconds=cfg.presign_expiry_seconds,
            )
            share_url = s3_presign(
                bucket=cfg.s3_bucket,
                key=share_key,
                expires_in_seconds=cfg.presign_expiry_seconds,
            )
            presigned_items.append((thumb_url, share_url))

        index_for_s3 = session_dir / "index.s3.html"
        build_index_html_presigned(session_id=session_id, items=presigned_items, out_path=index_for_s3)
        upload_one(index_for_s3, f"{prefix}/index.html")

        # Presign
        index_key = f"{prefix}/index.html"
        url = s3_presign(
            bucket=cfg.s3_bucket,
            key=index_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        share_txt.write_text(url + os.linesep, encoding="utf-8")
        logger.info(f"Presigned URL (expires in {cfg.presign_expiry_seconds}s): {url}")

        return sp, url
    finally:
        conn.close()


