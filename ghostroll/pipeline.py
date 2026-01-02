from __future__ import annotations

import json
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
from .gallery import build_index_html_from_items, build_index_html_loading, build_index_html_presigned
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


def _db_get_known_sizes(conn: sqlite3.Connection) -> set[int]:
    """Get all known file sizes from database for fast pre-filtering."""
    rows = conn.execute("SELECT DISTINCT size_bytes FROM ingested_files").fetchall()
    return {row["size_bytes"] for row in rows}


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
    try:
        for p in sorted(dcim_dir.rglob("*")):
            try:
                if p.is_file() and media.is_media(p):
                    out.append(p)
            except (OSError, IOError):
                # File/directory became inaccessible during iteration, skip it
                continue
    except (OSError, IOError):
        # Volume became inaccessible during directory traversal, return what we have
        pass
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
    try:
        if not dcim_dir.is_dir():
            raise PipelineError(f"Volume has no DCIM directory: {dcim_dir}")
    except (OSError, IOError) as e:
        raise PipelineError(f"Volume is not accessible (may be stale mount): {dcim_dir}: {e}")

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

        # Fast pre-filter: check file sizes first (much faster than hashing)
        # Files with sizes not in the database are definitely new and don't need duplicate checking
        logger.info(f"Pre-filtering {len(all_media)} files by size...")
        known_sizes = _db_get_known_sizes(conn)
        logger.debug(f"Database contains {len(known_sizes)} unique file sizes")
        
        # Get file sizes quickly (stat is very fast, no I/O)
        files_with_sizes: list[tuple[Path, int]] = []
        for p in all_media:
            try:
                size = p.stat().st_size
                files_with_sizes.append((p, size))
            except OSError:
                # File might have been deleted, skip it
                logger.debug(f"  Skipped (cannot stat): {p.name}")
                continue
        
        # Split files into two groups:
        # 1. Files with new sizes - definitely new, skip hashing (will hash during copy)
        # 2. Files with known sizes - might be duplicates, need to hash to check
        files_to_check: list[tuple[Path, int]] = []  # Potential duplicates (known size)
        files_new_size: list[tuple[Path, int]] = []  # Definitely new (new size)
        
        for p, size in files_with_sizes:
            if size not in known_sizes:
                # Size not in DB - definitely a new file, skip hashing (will hash during copy)
                files_new_size.append((p, size))
            else:
                # Size matches - might be duplicate, need to hash to confirm
                files_to_check.append((p, size))
        
        logger.info(f"Pre-filter results: {len(files_new_size)} new by size (skipping hash), {len(files_to_check)} potential duplicates")
        
        # Hash files that might be duplicates (parallelized)
        def _hash_one(item: tuple[Path, int]) -> tuple[Path, str, int] | None:
            p, size = item
            try:
                sha, _ = sha256_file(p)
                return (p, sha, size)
            except (OSError, IOError) as e:
                # File/volume became inaccessible (e.g., SD card removed)
                logger.debug(f"  Skipped (cannot hash, volume may be inaccessible): {p.name}: {e}")
                return None
        
        # Hash potential duplicates first (these need duplicate checking)
        hashed_files: list[tuple[Path, str, int]] = []
        if files_to_check:
            logger.info(f"Hashing {len(files_to_check)} files to check for duplicates...")
            hash_workers = min(4, max(1, cfg.process_workers))
            with ThreadPoolExecutor(max_workers=hash_workers) as ex:
                futures = {ex.submit(_hash_one, item): item for item in files_to_check}
                for i, fut in enumerate(as_completed(futures), 1):
                    try:
                        result = fut.result()
                        if result is None:
                            # File became inaccessible, skip it
                            continue
                        p, sha, size = result
                        logger.debug(f"Hashing [{i}/{len(files_to_check)}]: {p.name}")
                        hashed_files.append((p, sha, size))
                    except Exception as e:
                        # Handle any unexpected errors from the future
                        item = futures[fut]
                        logger.debug(f"  Skipped (error hashing): {item[0].name}: {e}")
                        continue
        
        # Batch check database for duplicates (more efficient than one-by-one)
        all_shas = {sha for (_, sha, _) in hashed_files}
        existing_shas: set[str] = set()
        if all_shas:
            logger.debug("Checking database for duplicate hashes...")
            placeholders = ",".join("?" * len(all_shas))
            existing_rows = conn.execute(
                f"SELECT sha256 FROM ingested_files WHERE sha256 IN ({placeholders})",
                tuple(all_shas)
            ).fetchall()
            existing_shas = {row["sha256"] for row in existing_rows}
        
        # Collect new files: files with known sizes that aren't duplicates, and files with new sizes (hash deferred)
        new_files: list[tuple[Path, str | None, int]] = []  # sha can be None for files_new_size (will hash during copy)
        skipped = 0
        
        # Check hashed files for duplicates
        for p, sha, size in hashed_files:
            if sha in existing_shas:
                skipped += 1
                logger.debug(f"  Skipped (already ingested): {p.name}")
                continue
            new_files.append((p, sha, size))
            logger.debug(f"  New file: {p.name} ({size:,} bytes, SHA256: {sha[:16]}...)")
        
        # Add files with new sizes (hash will be computed during copy, not upfront)
        for p, size in files_new_size:
            new_files.append((p, None, size))  # None means hash will be computed during copy
            logger.debug(f"  New file (by size, hash deferred): {p.name} ({size:,} bytes)")

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
        total_size = sum(size for (_, _, size) in new_files)
        copied_size = 0
        logger.info(f"Copying {len(new_files)} files ({total_size:,} bytes total) to {originals_dir}...")
        
        # Parallelize file copying (I/O bound operation)
        def _copy_one(item: tuple[Path, str | None, int]) -> tuple[bool, int, Path, str]:
            src, sha, size = item
            rel = _safe_rel_under(dcim_dir, src)
            dst = originals_dir / "DCIM" / rel
            
            # If hash is None (file with new size), compute it now (before copy for efficiency)
            if sha is None:
                sha, _ = sha256_file(src)
            
            copied_file = _copy2_ignore_existing(src, dst)
            return (copied_file, size if copied_file else 0, src, sha)
        
        copy_workers = min(4, max(1, cfg.process_workers))  # Use fewer workers for copying
        db_inserts: list[tuple[str, int, str]] = []  # (sha, size, source_hint)
        # Map to collect hashes computed during copy (for files with new sizes)
        computed_hashes: dict[Path, str] = {}
        
        with ThreadPoolExecutor(max_workers=copy_workers) as ex:
            futures = {ex.submit(_copy_one, item): item for item in new_files}
            for i, fut in enumerate(as_completed(futures), 1):
                item = futures[fut]
                was_copied, file_size, src, sha = fut.result()
                # Store computed hash (for files with new sizes that had None hash)
                computed_hashes[src] = sha
                if was_copied:
                    copied += 1
                    copied_size += file_size
                    logger.info(f"  Copied [{i}/{len(new_files)}]: {src.name} -> {originals_dir / 'DCIM' / _safe_rel_under(dcim_dir, src)} ({file_size:,} bytes)")
                else:
                    logger.debug(f"  Skipped (already exists): {src.name}")
                # Collect DB inserts for batch operation
                db_inserts.append((sha, item[2], str(src)))
        
        # Update new_files with computed hashes (all hashes are now in computed_hashes)
        new_files_with_hashes: list[tuple[Path, str, int]] = [
            (p, computed_hashes[p], size) for (p, sha, size) in new_files
        ]
        
        # Batch insert into database (more efficient than one-by-one)
        logger.debug(f"Marking {len(db_inserts)} files as ingested in database...")
        for sha, size, source_hint in db_inserts:
            _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=source_hint)
        conn.commit()
        logger.info(f"Ingested originals: {copied} files copied ({copied_size:,} bytes) -> {originals_dir}")

        # Process: only JPEGs that are newly ingested this run (fast + matches "new since last time" UX).
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="process",
                    message="Generating share images + thumbnails…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"new": len(new_files_with_hashes), "skipped": skipped, "processed_done": 0, "processed_total": 0},
                )
            )
        new_sha_set = {sha for (_p, sha, _s) in new_files_with_hashes}

        # Map from DCIM source path to sha for quick membership
        src_sha: dict[Path, str] = {p: sha for (p, sha, _s) in new_files_with_hashes}

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
            logger.debug(f"Processing image: {src.name}")
            if not share_out.exists():
                logger.debug(f"  Generating share image: {share_out.name} (max {cfg.share_max_long_edge}px, quality {cfg.share_quality})")
                render_jpeg_derivative(
                    src,
                    dst_path=share_out,
                    max_long_edge=cfg.share_max_long_edge,
                    quality=cfg.share_quality,
                )
            else:
                logger.debug(f"  Share image exists, skipping: {share_out.name}")
            if not thumb_out.exists():
                logger.debug(f"  Generating thumbnail: {thumb_out.name} (max {cfg.thumb_max_long_edge}px, quality {cfg.thumb_quality})")
                render_jpeg_derivative(
                    src,
                    dst_path=thumb_out,
                    max_long_edge=cfg.thumb_max_long_edge,
                    quality=cfg.thumb_quality,
                )
            else:
                logger.debug(f"  Thumbnail exists, skipping: {thumb_out.name}")
            ex = extract_basic_exif(src)
            sort_ts = ex.captured_at.timestamp() if ex.captured_at is not None else 9e18
            title = rel.as_posix()
            parts = [p for p in [ex.captured_at_display, ex.camera] if p]
            subtitle = " · ".join(parts)
            logger.debug(f"  Processed: {src.name} -> {rel.as_posix()}")
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
                        counts={"new": len(new_files_with_hashes), "skipped": skipped, "processed_done": 0, "processed_total": len(proc_tasks)},
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
                    logger.debug(f"Processed [{processed}/{len(proc_tasks)}]: {rel_posix}")
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
                                    "new": len(new_files_with_hashes),
                                    "skipped": skipped,
                                    "processed_done": processed,
                                    "processed_total": len(proc_tasks),
                                },
                            )
                        )
        logger.info(f"Processed JPEGs (share+thumb): {processed}")

        # Build a downloadable zip of share images (for local + S3 download-all).
        logger.info(f"Building share.zip from {derived_share_dir}...")
        _build_share_zip(share_dir=derived_share_dir, out_zip=share_zip)
        zip_size = share_zip.stat().st_size if share_zip.exists() else 0
        logger.info(f"Created share.zip: {share_zip} ({zip_size:,} bytes)")

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

        upload_failures: list[str] = []

        def _upload_one(task: tuple[Path, str]) -> tuple[bool, str | None]:
            local, key = task
            file_size = local.stat().st_size if local.exists() else 0
            logger.debug(f"Uploading: {local.name} -> s3://{cfg.s3_bucket}/{key} ({file_size:,} bytes)")

            def do(conn2: sqlite3.Connection):
                sha, size = sha256_file(local)
                prev_sha = _db_uploaded_sha(conn2, s3_key=key)
                if prev_sha == sha:
                    logger.debug(f"  Skipped (already uploaded): {local.name}")
                    return ("skipped", None)
                logger.debug(f"  Uploading {local.name} to s3://{cfg.s3_bucket}/{key}...")
                s3_cp(local, bucket=cfg.s3_bucket, key=key, retries=3)
                _db_mark_uploaded(conn2, s3_key=key, local_sha256=sha, size_bytes=size)
                conn2.commit()
                logger.debug(f"  Uploaded: {local.name}")
                return ("uploaded", None)

            try:
                outcome, _ = _db_with_retry(cfg.db_path, do)
                return (outcome == "uploaded", None)
            except Exception as e:
                logger.error(f"  Upload failed: {local.name} -> s3://{cfg.s3_bucket}/{key}: {e}")
                return (False, f"{local} -> s3://{cfg.s3_bucket}/{key}: {e}")

        # Snappy UX: publish the gallery link first (loading page), then upload photos.
        # We upload a small status.json + a lightweight loading index.html to the FINAL S3 key
        # (prefix/index.html), presign it, and show the QR immediately. Later we overwrite that
        # same key with the final presigned gallery page.
        status_key = f"{prefix}/status.json"
        s3_index_key = f"{prefix}/index.html"

        logger.info(f"Publishing initial gallery link (loading page)...")
        s3_status_local = session_dir / "status.s3.json"
        s3_status_local.write_text(
            json.dumps(
                {
                    "uploading": True,
                    "message": "Upload in progress…",
                    "session_id": session_id,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        logger.debug(f"Uploading status.json: {status_key}")
        uploaded, err = _upload_one((s3_status_local, status_key))
        if uploaded:
            uploaded_ok += 1
            logger.debug(f"Status.json uploaded successfully")
        if err:
            upload_failures.append(err)

        logger.debug(f"Generating presigned URL for status.json...")
        status_url = s3_presign(
            bucket=cfg.s3_bucket,
            key=status_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        logger.debug(f"Status URL: {status_url[:80]}...")

        index_loading = session_dir / "index.loading.s3.html"
        logger.debug(f"Building loading page HTML...")
        build_index_html_loading(
            session_id=session_id,
            status_json_url=status_url,
            poll_seconds=cfg.poll_seconds,
            out_path=index_loading,
        )
        logger.debug(f"Uploading loading page: {s3_index_key}")
        uploaded, err = _upload_one((index_loading, s3_index_key))
        if uploaded:
            uploaded_ok += 1
        if err:
            upload_failures.append(err)

        if upload_failures:
            logger.error("Upload failures:\n" + "\n".join(upload_failures))
            if status is not None:
                status.write(
                    Status(
                        state="error",
                        step="upload",
                        message="Failed to publish gallery link.",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"uploaded": uploaded_ok},
                    )
                )
            raise PipelineError("Failed to publish gallery link. See log for details.")

        # Presign the (loading) index now so we can share immediately.
        logger.info(f"Generating presigned share URL for gallery...")
        url = s3_presign(
            bucket=cfg.s3_bucket,
            key=s3_index_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        share_txt.write_text(url + os.linesep, encoding="utf-8")
        logger.info(f"Share URL (available immediately; expires in {cfg.presign_expiry_seconds}s): {url}")

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
                    state="running",
                    step="upload",
                    message="Gallery link ready. Uploading photos…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"uploaded_done": uploaded_ok, "uploaded_total": 0},
                    url=url,
                )
            )

        # Build upload tasks from processed files (avoid redundant directory scans)
        upload_tasks: list[tuple[Path, str]] = []
        # Use the gallery items we already have to build upload tasks efficiently
        for thumb_href, share_href, _title, _subtitle in local_items:
            # Convert "derived/thumbs/100CANON/IMG_0001.jpg" -> actual paths
            thumb_rel = thumb_href.replace("derived/thumbs/", "")
            share_rel = share_href.replace("derived/share/", "")
            upload_tasks.append((derived_thumbs_dir / thumb_rel, f"{prefix}/thumbs/{thumb_rel}"))
            upload_tasks.append((derived_share_dir / share_rel, f"{prefix}/share/{share_rel}"))
        # Also upload the "download all" zip
        upload_tasks.append((share_zip, f"{prefix}/share.zip"))

        # Map gallery items to their S3 keys for progressive updates.
        # gallery_items_local has (thumb_href, share_href, title, subtitle, sort_ts)
        # where hrefs are like "derived/thumbs/100CANON/IMG_0001.jpg"
        gallery_to_s3_keys: dict[tuple[str, str, str, str, float], tuple[str, str]] = {}
        for thumb_href, share_href, title, subtitle, sort_ts in gallery_items_local:
            # Convert "derived/thumbs/100CANON/IMG_0001.jpg" -> "100CANON/IMG_0001.jpg"
            thumb_rel = thumb_href.replace("derived/thumbs/", "")
            share_rel = share_href.replace("derived/share/", "")
            gallery_to_s3_keys[(thumb_href, share_href, title, subtitle, sort_ts)] = (
                f"{prefix}/thumbs/{thumb_rel}",
                f"{prefix}/share/{share_rel}",
            )

        def _refresh_gallery_progressively(uploaded_keys: set[str]) -> None:
            """Build and upload a partial gallery with only images that have both thumb and share uploaded."""
            ready_items: list[tuple[str, str, str, str, float]] = []
            for item, (thumb_key, share_key) in gallery_to_s3_keys.items():
                if thumb_key in uploaded_keys and share_key in uploaded_keys:
                    ready_items.append(item)

            if not ready_items:
                return  # Nothing ready yet

            # Sort by capture time (same as final gallery)
            ready_items.sort(key=lambda x: (x[4], x[2]))
            # Extract relative paths from hrefs: "derived/thumbs/100CANON/IMG_0001.jpg" -> "100CANON/IMG_0001.jpg"
            ready_rel_paths: list[tuple[str, str, str, str]] = []
            for item in ready_items:
                thumb_href, share_href, title, subtitle = item[0], item[1], item[2], item[3]
                thumb_rel = thumb_href.replace("derived/thumbs/", "")
                share_rel = share_href.replace("derived/share/", "")
                ready_rel_paths.append((thumb_rel, share_rel, title, subtitle))

            # Presign URLs for ready images
            presigned_ready: list[tuple[str, str, str, str]] = []
            for thumb_rel, share_rel, title, subtitle in ready_rel_paths:
                thumb_key = f"{prefix}/thumbs/{thumb_rel}"
                share_key = f"{prefix}/share/{share_rel}"
                try:
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
                    presigned_ready.append((thumb_url, share_url, title, subtitle))
                except Exception as e:
                    logger.warning(f"Failed to presign {thumb_key}: {e}")
                    continue

            if not presigned_ready:
                return

            # Build partial gallery (no download zip yet if not uploaded)
            download_href = None
            if f"{prefix}/share.zip" in uploaded_keys:
                try:
                    download_href = s3_presign(
                        bucket=cfg.s3_bucket,
                        key=f"{prefix}/share.zip",
                        expires_in_seconds=cfg.presign_expiry_seconds,
                    )
                except Exception as e:
                    logger.warning(f"Failed to presign share.zip: {e}")

            index_partial = session_dir / "index.partial.s3.html"
            build_index_html_presigned(
                session_id=session_id,
                items=presigned_ready,
                download_href=download_href,
                out_path=index_partial,
            )

            # Upload the partial gallery (overwrites the loading page or previous partial)
            uploaded, err = _upload_one((index_partial, s3_index_key))
            if uploaded:
                logger.info(f"Refreshed gallery with {len(presigned_ready)}/{len(gallery_items_local)} images")
            elif err:
                logger.warning(f"Failed to upload partial gallery: {err}")

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
            uploaded_keys: set[str] = set()
            last_gallery_refresh = time.time()
            GALLERY_REFRESH_INTERVAL = 30.0  # seconds

            with ThreadPoolExecutor(max_workers=max(1, cfg.upload_workers)) as ex:
                futures = {ex.submit(_upload_one, t): t for t in upload_tasks}
                last_ui = time.time()
                for fut in as_completed(futures):
                    uploaded, err = fut.result()
                    task = futures[fut]
                    if uploaded:
                        uploaded_ok += 1
                        # Track which key was uploaded (task is (Path, s3_key))
                        uploaded_keys.add(task[1])
                        logger.info(f"Uploaded [{uploaded_ok}/{len(upload_tasks)}]: {task[0].name} -> {task[1]}")
                    if err:
                        upload_failures.append(err)
                        logger.error(f"Upload failed [{uploaded_ok}/{len(upload_tasks)}]: {task[0].name} -> {task[1]}: {err}")

                    # Periodic gallery refresh (every 30 seconds)
                    now = time.time()
                    if now - last_gallery_refresh >= GALLERY_REFRESH_INTERVAL:
                        last_gallery_refresh = now
                        try:
                            _refresh_gallery_progressively(uploaded_keys)
                        except Exception as e:
                            logger.warning(f"Failed to refresh gallery progressively: {e}")

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

            # Final progressive refresh after all uploads complete (in case some finished in last 30s)
            try:
                _refresh_gallery_progressively(uploaded_keys)
            except Exception as e:
                logger.warning(f"Failed to do final progressive gallery refresh: {e}")

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
            logger.debug(f"Presigning: {rel.as_posix()}")
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
                    result = fut.result()
                    presigned_items.append(result)
                    done += 1
                    logger.debug(f"Presigned [{done}/{len(thumb_files)}]: {result[2]}")
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
        logger.debug(f"Presigning share.zip...")
        download_zip_url = s3_presign(
            bucket=cfg.s3_bucket,
            key=f"{prefix}/share.zip",
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        logger.debug(f"Presigned share.zip URL")
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
        logger.info(f"Building final presigned gallery with {len(presigned_ui)} images...")
        build_index_html_presigned(
            session_id=session_id,
            items=presigned_ui,
            download_href=download_zip_url,
            out_path=index_for_s3,
        )
        logger.info(f"Uploading final gallery to s3://{cfg.s3_bucket}/{s3_index_key}...")
        # Upload the final index.html (force content-based dedupe)
        uploaded, err = _upload_one((index_for_s3, s3_index_key))
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

        # Mark S3 status as complete so the early "loading" page auto-refreshes into the final gallery.
        logger.info("Marking upload as complete in status.json...")
        s3_status_local.write_text(
            json.dumps(
                {
                    "uploading": False,
                    "message": "Upload complete.",
                    "session_id": session_id,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        uploaded, err = _upload_one((s3_status_local, status_key))
        if uploaded:
            uploaded_ok += 1
        if err:
            logger.warning(f"Failed to update S3 status.json to complete: {err}")

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
                        "new": len(new_files_with_hashes),
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


