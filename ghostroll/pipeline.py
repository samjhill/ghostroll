from __future__ import annotations

import os
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import media
from .aws_cli import AwsCliError, s3_cp, s3_presign
from .config import Config
from .db import connect
from .exif_utils import extract_basic_exif
from .gallery import build_index_html_from_items, build_index_html_presigned
from .hashing import sha256_file
from .image_processing import render_jpeg_derivative
from .logging_utils import attach_session_logfile
from .qr import QrError, render_qr_ascii, write_qr_png
from .status import Status, StatusWriter


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


def _build_share_zip(*, share_dir: Path, out_zip: Path) -> None:
    """
    Creates a zip file containing the share/ directory contents.
    """
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted([p for p in share_dir.rglob("*") if p.is_file()]):
            rel = p.relative_to(share_dir)
            zf.write(p, arcname=str(Path("share") / rel))


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

def _db_with_retry(db_path: Path, fn, *, retries: int = 10, backoff: float = 0.05):
    """
    SQLite can briefly lock under concurrent writes. This helper retries a small number of times.
    """
    last_exc = None
    for i in range(retries):
        try:
            conn = connect(db_path)
            try:
                return fn(conn)
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_exc = e
            time.sleep(backoff * (i + 1))
    raise last_exc  # type: ignore[misc]


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
    status: StatusWriter | None = None,
    always_create_session: bool = False,
    session_id: str | None = None,
) -> tuple[SessionPaths | None, str | None]:
    """
    Returns (session_paths or None if no-op, presigned_url or None).
    """
    dcim_dir = volume_path / "DCIM"
    if not dcim_dir.is_dir():
        raise PipelineError(f"Volume has no DCIM directory: {dcim_dir}")

    if status is not None:
        status.write(
            Status(
                state="running",
                step="scan",
                message="Scanning DCIM for media…",
                session_id=session_id,
                volume=str(volume_path),
            )
        )

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
            if status is not None:
                status.write(
                    Status(
                        state="idle",
                        step="noop",
                        message="No new files detected.",
                        volume=str(volume_path),
                        counts={"discovered": len(all_media), "new": 0, "skipped": skipped},
                    )
                )
            return None, None

        session_id = session_id or _session_id_now()
        session_dir = cfg.sessions_dir / session_id
        originals_dir = session_dir / "originals"
        derived_share_dir = session_dir / "derived" / "share"
        derived_thumbs_dir = session_dir / "derived" / "thumbs"
        index_html = session_dir / "index.html"
        share_zip = session_dir / "share.zip"
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
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="ingest",
                    message="Copying originals…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"discovered": len(all_media), "new": len(new_files), "skipped": skipped},
                )
            )
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
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="process",
                    message="Generating share images + thumbnails…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"new": len(new_files), "skipped": skipped, "processed_done": 0, "processed_total": 0},
                )
            )
        new_sha_set = {sha for (_p, sha, _s) in new_files}

        # Map from DCIM source path to sha for quick membership
        src_sha: dict[Path, str] = {p: sha for (p, sha, _s) in new_files}

        # Derived outputs mirror DCIM relpath and normalize to .jpg
        processed = 0
        proc_tasks: list[tuple[Path, Path, Path, Path]] = []
        for src in jpeg_sources:
            sha = src_sha.get(src)
            if sha is None or sha not in new_sha_set:
                continue
            rel = _safe_rel_under(dcim_dir, src).with_suffix(".jpg")
            proc_tasks.append((src, rel, derived_share_dir / rel, derived_thumbs_dir / rel))

        def _process_one(task: tuple[Path, Path, Path, Path]) -> tuple[str, float, str, str]:
            src, rel, share_out, thumb_out = task
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
            ex = extract_basic_exif(src)
            sort_ts = ex.captured_at.timestamp() if ex.captured_at is not None else 9e18
            title = rel.as_posix()
            parts = [p for p in [ex.captured_at_display, ex.camera] if p]
            subtitle = " · ".join(parts)
            return (rel.as_posix(), sort_ts, title, subtitle)

        gallery_items_local: list[tuple[str, str, str, str, float]] = []
        if proc_tasks:
            logger.info(f"Processing {len(proc_tasks)} new JPEGs with {cfg.process_workers} workers...")
            if status is not None:
                status.write(
                    Status(
                        state="running",
                        step="process",
                        message="Generating share images + thumbnails…",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"new": len(new_files), "skipped": skipped, "processed_done": 0, "processed_total": len(proc_tasks)},
                    )
                )
            with ThreadPoolExecutor(max_workers=max(1, cfg.process_workers)) as ex:
                futures = [ex.submit(_process_one, t) for t in proc_tasks]
                last_ui = time.time()
                for fut in as_completed(futures):
                    rel_posix, sort_ts, title, subtitle = fut.result()
                    thumb_href = f"derived/thumbs/{rel_posix}"
                    share_href = f"derived/share/{rel_posix}"
                    gallery_items_local.append((thumb_href, share_href, title, subtitle, sort_ts))
                    processed += 1
                    if status is not None and (time.time() - last_ui) > 0.75:
                        last_ui = time.time()
                        status.write(
                            Status(
                                state="running",
                                step="process",
                                message="Generating share images + thumbnails…",
                                session_id=session_id,
                                volume=str(volume_path),
                                counts={
                                    "new": len(new_files),
                                    "skipped": skipped,
                                    "processed_done": processed,
                                    "processed_total": len(proc_tasks),
                                },
                            )
                        )
        logger.info(f"Processed JPEGs (share+thumb): {processed}")

        # Build a downloadable zip of share images (for local + S3 download-all).
        _build_share_zip(share_dir=derived_share_dir, out_zip=share_zip)

        # Gallery (local): sort by capture time (if available) then filename.
        gallery_items_local.sort(key=lambda x: (x[4], x[2]))
        local_items = [(a, b, c, d) for (a, b, c, d, _ts) in gallery_items_local]
        build_index_html_from_items(
            session_id=session_id,
            items=local_items,
            download_href="share.zip",
            out_path=index_html,
        )
        logger.info(f"Generated gallery: {index_html}")

        # Upload (retry-tolerant) with per-key upload dedupe (idempotent if re-run)
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="upload",
                    message="Uploading to S3…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"uploaded_done": 0, "uploaded_total": 0},
                )
            )
        prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
        uploaded_ok = 0

        upload_tasks: list[tuple[Path, str]] = []
        for p in sorted(derived_share_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(derived_share_dir)
                upload_tasks.append((p, f"{prefix}/share/{rel.as_posix()}"))
        for p in sorted(derived_thumbs_dir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(derived_thumbs_dir)
                upload_tasks.append((p, f"{prefix}/thumbs/{rel.as_posix()}"))
        # Also upload the "download all" zip
        upload_tasks.append((share_zip, f"{prefix}/share.zip"))

        upload_failures: list[str] = []

        def _upload_one(task: tuple[Path, str]) -> tuple[bool, str | None]:
            local, key = task

            def do(conn2: sqlite3.Connection):
                sha, size = sha256_file(local)
                prev_sha = _db_uploaded_sha(conn2, s3_key=key)
                if prev_sha == sha:
                    return ("skipped", None)
                s3_cp(local, bucket=cfg.s3_bucket, key=key, retries=3)
                _db_mark_uploaded(conn2, s3_key=key, local_sha256=sha, size_bytes=size)
                conn2.commit()
                return ("uploaded", None)

            try:
                outcome, _ = _db_with_retry(cfg.db_path, do)
                return (outcome == "uploaded", None)
            except Exception as e:
                return (False, f"{local} -> s3://{cfg.s3_bucket}/{key}: {e}")

        if upload_tasks:
            logger.info(f"Uploading {len(upload_tasks)} objects with {cfg.upload_workers} workers...")
            if status is not None:
                status.write(
                    Status(
                        state="running",
                        step="upload",
                        message="Uploading to S3…",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"uploaded_done": 0, "uploaded_total": len(upload_tasks)},
                    )
                )
            with ThreadPoolExecutor(max_workers=max(1, cfg.upload_workers)) as ex:
                futures = {ex.submit(_upload_one, t): t for t in upload_tasks}
                last_ui = time.time()
                for fut in as_completed(futures):
                    uploaded, err = fut.result()
                    if uploaded:
                        uploaded_ok += 1
                    if err:
                        upload_failures.append(err)
                    if status is not None and (time.time() - last_ui) > 0.75:
                        last_ui = time.time()
                        status.write(
                            Status(
                                state="running",
                                step="upload",
                                message="Uploading to S3…",
                                session_id=session_id,
                                volume=str(volume_path),
                                counts={"uploaded_done": uploaded_ok, "uploaded_total": len(upload_tasks)},
                            )
                        )

        if upload_failures:
            logger.error("Upload failures:\n" + "\n".join(upload_failures))
            if status is not None:
                status.write(
                    Status(
                        state="error",
                        step="upload",
                        message=f"Upload failed for {len(upload_failures)} objects.",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"uploaded": uploaded_ok},
                    )
                )
            raise PipelineError(f"Upload failed for {len(upload_failures)} objects. See log for details.")

        # Build an S3-shareable gallery that embeds presigned URLs for assets (bucket remains private).
        # We keep the local index.html (relative paths) for offline/local browsing.
        presigned_items: list[tuple[str, str, str, str]] = []
        thumb_files = sorted([p for p in derived_thumbs_dir.rglob("*") if p.is_file()])
        logger.info(f"Generating presigned asset URLs for {len(thumb_files)} images with {cfg.presign_workers} workers...")
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="presign",
                    message="Generating share link…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"presigned_done": 0, "presigned_total": len(thumb_files) + 1},  # +1 for share.zip
                )
            )

        def _presign_one(t: Path) -> tuple[str, str, str, str, float]:
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
            title = rel.as_posix()
            return (thumb_url, share_url, title, "", 9e18)

        if thumb_files:
            with ThreadPoolExecutor(max_workers=max(1, cfg.presign_workers)) as ex:
                futures = [ex.submit(_presign_one, t) for t in thumb_files]
                done = 0
                last_ui = time.time()
                for fut in as_completed(futures):
                    presigned_items.append(fut.result())
                    done += 1
                    if status is not None and (time.time() - last_ui) > 0.75:
                        last_ui = time.time()
                        status.write(
                            Status(
                                state="running",
                                step="presign",
                                message="Generating share link…",
                                session_id=session_id,
                                volume=str(volume_path),
                                counts={"presigned_done": done, "presigned_total": len(thumb_files) + 1},
                            )
                        )

        # Presign the download zip
        download_zip_url = s3_presign(
            bucket=cfg.s3_bucket,
            key=f"{prefix}/share.zip",
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="presign",
                    message="Generating share link…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"presigned_done": len(thumb_files) + 1, "presigned_total": len(thumb_files) + 1},
                )
            )

        presigned_items.sort(key=lambda x: (x[4], x[2]))
        presigned_ui = [(a, b, c, d) for (a, b, c, d, _ts) in presigned_items]

        index_for_s3 = session_dir / "index.s3.html"
        build_index_html_presigned(
            session_id=session_id,
            items=presigned_ui,
            download_href=download_zip_url,
            out_path=index_for_s3,
        )
        # Upload the final index.html (force content-based dedupe)
        uploaded, err = _upload_one((index_for_s3, f"{prefix}/index.html"))
        if uploaded:
            uploaded_ok += 1
        if err:
            upload_failures.append(err)
            logger.error("Upload failures:\n" + "\n".join(upload_failures))
            if status is not None:
                status.write(
                    Status(
                        state="error",
                        step="upload",
                        message="Upload failed for index.html.",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"uploaded": uploaded_ok},
                    )
                )
            raise PipelineError("Upload failed for index.html. See log for details.")

        # Presign
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="presign",
                    message="Generating share link…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"uploaded": uploaded_ok},
                )
            )
        index_key = f"{prefix}/index.html"
        url = s3_presign(
            bucket=cfg.s3_bucket,
            key=index_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        share_txt.write_text(url + os.linesep, encoding="utf-8")
        logger.info(f"Presigned URL (expires in {cfg.presign_expiry_seconds}s): {url}")

        # QR code (nice-to-have): write a PNG into the session folder and print an ASCII QR in logs.
        try:
            qr_png = session_dir / "share-qr.png"
            write_qr_png(data=url, out_path=qr_png)
            logger.info(f"QR code written: {qr_png}")
            logger.info("\n" + render_qr_ascii(url))
        except QrError as e:
            logger.warning(str(e))

        if status is not None:
            status.write(
                Status(
                    state="done",
                    step="done",
                    message="Complete.",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={
                        "discovered": len(all_media),
                        "new": len(new_files),
                        "skipped": skipped,
                        "processed": processed,
                        "uploaded": uploaded_ok,
                    },
                    url=url,
                )
            )

        return sp, url
    finally:
        conn.close()


