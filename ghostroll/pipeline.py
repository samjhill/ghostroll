from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
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


def _db_get_failed_files(conn: sqlite3.Connection, *, dcim_dir: Path) -> set[Path]:
    """Get set of file paths that have consistently failed to hash."""
    # Get failed files that match files in this DCIM directory
    failed_rows = conn.execute(
        "SELECT file_path FROM failed_files WHERE failure_count >= 2"
    ).fetchall()
    failed_paths = set()
    for row in failed_rows:
        file_path_str = row["file_path"]
        # Try to match against current DCIM structure
        # file_path might be absolute or relative - try both
        try:
            p = Path(file_path_str)
            if p.is_absolute():
                # Check if it's under the current dcim_dir
                try:
                    rel = p.relative_to(dcim_dir)
                    if (dcim_dir / rel).exists():
                        failed_paths.add(dcim_dir / rel)
                except ValueError:
                    # Not under dcim_dir, skip
                    pass
            else:
                # Relative path, try under dcim_dir
                candidate = dcim_dir / p
                if candidate.exists():
                    failed_paths.add(candidate)
        except Exception:
            # Invalid path, skip
            pass
    return failed_paths


def _db_mark_failed_file(
    conn: sqlite3.Connection, *, file_path: Path, size_bytes: int, dcim_dir: Path
) -> None:
    """Mark a file as failed to hash, or increment failure count."""
    # Store relative path for portability
    try:
        rel_path = str(file_path.relative_to(dcim_dir))
    except ValueError:
        # If not under dcim_dir, store absolute path
        rel_path = str(file_path)
    
    now = _utc_now()
    conn.execute(
        "INSERT INTO failed_files(file_path, size_bytes, first_failed_utc, last_failed_utc, failure_count) "
        "VALUES(?, ?, ?, ?, 1) "
        "ON CONFLICT(file_path) DO UPDATE SET "
        "last_failed_utc = ?, failure_count = failure_count + 1",
        (rel_path, size_bytes, now, now, now),
    )


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


def _iter_media_files(dcim_dir: Path, logger=None) -> list[Path]:
    """
    Recursively find all media files in the DCIM directory.
    Uses subprocess find command to bypass any Python filesystem caching.
    """
    out: list[Path] = []
    all_files_count = 0
    try:
        # Use subprocess find to bypass any Python filesystem caching
        # This should give us a fresh view of the filesystem
        result = subprocess.run(
            ["find", str(dcim_dir), "-type", "f"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            if logger:
                logger.warning(f"find command failed with return code {result.returncode}: {result.stderr}")
            # Fallback to os.walk if find fails
            for root, dirs, files in os.walk(str(dcim_dir)):
                root_path = Path(root)
                for filename in files:
                    all_files_count += 1
                    file_path = root_path / filename
                    try:
                        if media.is_media(file_path):
                            out.append(file_path)
                    except (OSError, IOError):
                        continue
        else:
            # Process find output
            all_find_files = result.stdout.splitlines()
            all_files_count = len([f for f in all_find_files if f.strip()])
            if logger:
                logger.debug(f"find command found {all_files_count} total files in {dcim_dir}")
            
            for line in all_find_files:
                if not line.strip():
                    continue
                file_path = Path(line.strip())
                try:
                    if file_path.is_file() and media.is_media(file_path):
                        out.append(file_path)
                except (OSError, IOError):
                    # File became inaccessible, skip it
                    continue
    except (OSError, IOError, subprocess.TimeoutExpired) as e:
        if logger:
            logger.warning(f"find command exception: {e}")
        # Fallback to os.walk if find fails or times out
        try:
            for root, dirs, files in os.walk(str(dcim_dir)):
                root_path = Path(root)
                for filename in files:
                    all_files_count += 1
                    file_path = root_path / filename
                    try:
                        if media.is_media(file_path):
                            out.append(file_path)
                    except (OSError, IOError):
                        continue
        except (OSError, IOError):
            pass
    
    if logger:
        logger.debug(f"Found {len(out)} media files out of {all_files_count} total files")
    return sorted(out)


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
            raise PipelineError(
                f"Volume has no DCIM directory: {dcim_dir}\n"
                f"  This usually means the SD card is not from a camera or the card structure is different.\n"
                f"  Expected: {volume_path}/DCIM/ directory\n"
                f"  Tip: Make sure you're using a camera-formatted SD card, or specify the correct volume path."
            )
    except (OSError, IOError) as e:
        error_code = getattr(e, 'errno', None)
        if error_code == 2:  # ENOENT - No such file or directory
            raise PipelineError(
                f"Volume path does not exist: {volume_path}\n"
                f"  The SD card may have been removed or unmounted.\n"
                f"  Try: Re-insert the SD card and wait for it to mount."
            ) from e
        elif error_code in (5, 13):  # EIO or EACCES - I/O error or Permission denied
            raise PipelineError(
                f"Volume is not accessible: {dcim_dir}\n"
                f"  This may be a stale mount (device removed but mount point still exists).\n"
                f"  Try: Unmount and re-insert the SD card, or restart the watch service."
            ) from e
        else:
            raise PipelineError(
                f"Volume is not accessible: {dcim_dir}\n"
                f"  Error: {e}\n"
                f"  Try: Check that the SD card is properly mounted and accessible."
            ) from e

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
        # Reconnect to the mount by accessing it (wakes up automount if needed)
        # This is important because we may have unmounted the volume earlier
        try:
            logger.debug(f"Reconnecting to mount point: {volume_path}")
            # Sync filesystem to ensure we see all files (flush kernel buffers)
            try:
                subprocess.run(["sync", str(volume_path)], timeout=5, check=False)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # sync command not available or timed out, continue anyway
                pass
            # Access the volume root to trigger automount refresh
            _ = volume_path.stat()
            # Access the DCIM directory to ensure it's accessible
            _ = dcim_dir.stat()
            # List the directory to force a fresh read
            dcim_listing = list(dcim_dir.iterdir())
            logger.debug(f"DCIM directory contains {len(dcim_listing)} items (directories/files)")
        except (OSError, IOError) as e:
            logger.warning(f"Cannot access mount/DCIM directory {dcim_dir}: {e}")
            error_code = getattr(e, 'errno', None)
            if error_code == 2:  # ENOENT
                raise PipelineError(
                    f"DCIM directory not found: {dcim_dir}\n"
                    f"  The directory may have been removed or the card was unmounted during processing.\n"
                    f"  Try: Re-insert the SD card and run again."
                ) from e
            elif error_code in (5, 13):  # EIO or EACCES
                raise PipelineError(
                    f"Cannot access DCIM directory: {dcim_dir}\n"
                    f"  The device may be disconnected or the filesystem is corrupted.\n"
                    f"  Try: Check the SD card connection and filesystem health."
                ) from e
            else:
                raise PipelineError(
                    f"Cannot access DCIM directory: {dcim_dir}\n"
                    f"  Error: {e}\n"
                    f"  Try: Verify the SD card is properly mounted and readable."
                ) from e
        
        logger.debug(f"Scanning DCIM directory: {dcim_dir}")
        all_media = _iter_media_files(dcim_dir, logger=logger)
        logger.info(f"Discovered {len(all_media)} media files in {dcim_dir}")
        if len(all_media) == 0:
            logger.warning(f"No media files found in {dcim_dir} - is the directory accessible?")
        elif len(all_media) > 0:
            # Show a sample of discovered files for debugging
            sample_files = [str(p.relative_to(dcim_dir)) for p in all_media[:5]]
            logger.debug(f"Sample files found: {', '.join(sample_files)}")
        jpeg_sources, raw_sources = _pair_prefer_jpeg(all_media)
        logger.info(f"File breakdown: {len(jpeg_sources)} JPEG candidates, {len(raw_sources)} RAW files")

        # Get file sizes and check database first to avoid unnecessary hashing
        files_with_sizes: list[tuple[Path, int]] = []
        for p in all_media:
            try:
                size = p.stat().st_size
                files_with_sizes.append((p, size))
            except OSError:
                # File might have been deleted, skip it
                logger.debug(f"  Skipped (cannot stat): {p.name}")
                continue
        
        # Pre-filter: check database for files we already know about (by size)
        # Also check for files that have consistently failed to hash (skip them)
        known_sizes = _db_get_known_sizes(conn)
        failed_files = _db_get_failed_files(conn, dcim_dir=dcim_dir)
        
        # Filter out files that have consistently failed to hash
        files_to_check: list[tuple[Path, int]] = []
        failed_count = 0
        for p, size in files_with_sizes:
            if p in failed_files:
                failed_count += 1
                logger.debug(f"  Skipping file that consistently fails to hash: {p.name}")
                continue
            files_to_check.append((p, size))
        
        if failed_count > 0:
            logger.info(f"Skipping {failed_count} files that consistently fail to hash (marked in database)")
        
        if known_sizes:
            logger.debug(f"Database contains {len(known_sizes)} unique file sizes - will check hashes after computing")
        
        # Before hashing from SD card, check if files already exist in recent session originals/
        # This prevents re-hashing if the process crashed during upload
        # Always check recent sessions (not just when session_id is None)
        existing_originals: dict[Path, Path] = {}  # Maps SD card path -> local originals path
        try:
            session_dirs = sorted(cfg.sessions_dir.glob("shoot-*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for recent_session_dir in session_dirs[:5]:  # Check last 5 sessions
                recent_originals = recent_session_dir / "originals" / "DCIM"
                if recent_originals.exists():
                    logger.debug(f"Checking {recent_session_dir.name} for already-copied files...")
                    try:
                        for orig_file in recent_originals.rglob("*"):
                            if orig_file.is_file():
                                # Reconstruct the SD card path from the originals path
                                rel_path = orig_file.relative_to(recent_originals)
                                sd_card_path = dcim_dir / rel_path
                                if sd_card_path.exists() and sd_card_path not in existing_originals:
                                    existing_originals[sd_card_path] = orig_file
                    except Exception as e:
                        logger.debug(f"Error checking {recent_session_dir.name}: {e}")
                        continue
            if existing_originals:
                logger.info(f"Found {len(existing_originals)} files already copied in recent sessions - will hash from local copies (faster)")
        except Exception as e:
            logger.debug(f"Error checking for existing originals: {e}")
        
        logger.info(f"Hashing {len(files_to_check)} files to check for duplicates...")
        
        # Hash all files to check for duplicates (parallelized)
        # Always hash from SD card to ensure we detect new/changed files correctly
        # (even if a local copy exists, the SD card file might be different/new)
        # Note: Don't use database connection in threads - collect failures and mark them after
        def _hash_one(item: tuple[Path, int]) -> tuple[Path, str, int] | None:
            p, size = item
            # Always hash from SD card to detect new/changed files
            # Note: We could optimize by checking if local copy SHA matches SD card,
            # but for correctness, we always hash from SD card to detect changes
            try:
                sha, _ = sha256_file(p)
                return (p, sha, size)
            except (OSError, IOError) as e:
                # File/volume became inaccessible (e.g., SD card removed or corrupted file)
                # Return None to indicate failure - we'll mark as failed in main thread
                # Don't use conn here - SQLite connections are not thread-safe
                logger.warning(f"  Cannot hash file (will mark as failed): {p.name}: {e}")
                return None
        
        hashed_files: list[tuple[Path, str, int]] = []
        failed_files: list[tuple[Path, int]] = []  # Files that failed to hash
        hash_workers = min(4, max(1, cfg.process_workers))
        with ThreadPoolExecutor(max_workers=hash_workers) as ex:
            futures = {ex.submit(_hash_one, item): item for item in files_to_check}
            for i, fut in enumerate(as_completed(futures), 1):
                try:
                    result = fut.result()
                    if result is None:
                        # File became inaccessible - collect for marking as failed
                        item = futures[fut]
                        failed_files.append((item[0], item[1]))
                        continue
                    p, sha, size = result
                    logger.debug(f"Hashing [{i}/{len(files_to_check)}]: {p.name}")
                    hashed_files.append((p, sha, size))
                except Exception as e:
                    # Handle any unexpected errors from the future
                    item = futures[fut]
                    logger.debug(f"  Skipped (error hashing): {item[0].name}: {e}")
                    failed_files.append((item[0], item[1]))
                    continue
        
        # Mark failed files in database (in main thread, not in worker threads)
        # SQLite connections are not thread-safe and must be used in the thread where created
        if failed_files:
            for p, size in failed_files:
                _db_mark_failed_file(conn, file_path=p, size_bytes=size, dcim_dir=dcim_dir)
            conn.commit()
            logger.info(f"Marked {len(failed_files)} files as failed in DB (will skip in future runs)")
        
        # Batch check database for duplicates (more efficient than one-by-one)
        all_shas = {sha for (_, sha, _) in hashed_files}
        existing_shas: set[str] = set()
        if all_shas:
            logger.debug(f"Checking database for {len(all_shas)} hashes...")
            placeholders = ",".join("?" * len(all_shas))
            existing_rows = conn.execute(
                f"SELECT sha256 FROM ingested_files WHERE sha256 IN ({placeholders})",
                tuple(all_shas)
            ).fetchall()
            existing_shas = {row["sha256"] for row in existing_rows}
            if existing_shas:
                logger.info(f"Found {len(existing_shas)} files already in database (will skip)")
            else:
                logger.debug(f"No files found in database (all {len(all_shas)} are new)")
        
        # Collect new files: all files that aren't duplicates
        new_files: list[tuple[Path, str, int]] = []  # All files are hashed, so sha is never None
        skipped = 0
        
        # Check hashed files for duplicates
        # Also handle crash recovery: if files were already copied to originals but not yet in DB,
        # mark them in DB immediately to prevent re-hashing on next run
        crash_recovery_count = 0
        for p, sha, size in hashed_files:
            if sha in existing_shas:
                skipped += 1
                logger.debug(f"  Skipped (already ingested): {p.name} (SHA256: {sha[:16]}...)")
                continue
            
            # Check if file was already copied to originals but not in DB (crash recovery scenario)
            # Only mark as ingested if the local copy has the same SHA as the SD card file
            # This handles the case where the process crashed after copying but before DB update
            if p in existing_originals:
                local_copy = existing_originals[p]
                try:
                    local_sha, _ = sha256_file(local_copy)
                    if local_sha == sha:
                        # Local copy matches SD card - this is crash recovery
                        logger.info(f"  File already copied but not in DB - marking as ingested (crash recovery): {p.name}")
                        _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=str(p))
                        crash_recovery_count += 1
                        # Still add to new_files so it gets processed/uploaded
                        # (the file exists in originals but may not be processed/uploaded yet)
                    else:
                        # Local copy differs from SD card - SD card file is new/changed
                        logger.debug(f"  File in originals but SHA differs - treating SD card file as new: {p.name}")
                except (OSError, IOError):
                    # Can't hash local copy - treat SD card file as new
                    logger.debug(f"  Cannot hash local copy - treating SD card file as new: {p.name}")
            
            new_files.append((p, sha, size))
            logger.info(f"  New file (not in DB): {p.name} ({size:,} bytes, SHA256: {sha[:16]}...)")
        
        # Commit any crash recovery marks
        if crash_recovery_count > 0:
            conn.commit()
            logger.info(f"Marked {crash_recovery_count} files as ingested in DB (crash recovery - prevents re-hashing on next run)")

        logger.info(f"Duplicate check complete: {len(new_files)} new files, {skipped} skipped (already in DB)")
        logger.debug(f"  Total hashed files: {len(hashed_files)}")
        logger.debug(f"  Files in database (existing_shas): {len(existing_shas)}")
        logger.debug(f"  New files to process: {len(new_files)}")
        logger.debug(f"  Skipped files: {skipped}")
        
        # Log summary of what happened
        if skipped > 0:
            logger.info(f"  → {skipped} files were already ingested (skipped processing)")
        if len(new_files) == 0 and skipped > 0:
            logger.info(f"  → All files already processed - no work needed")
        elif len(new_files) == 0 and skipped == 0:
            logger.warning(f"  → No new files detected, but also no skipped files - this is unexpected!")
        
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

        # Early QR code generation: publish the gallery link (loading page) immediately after session creation,
        # before processing files, so the QR code is available as soon as possible.
        prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
        uploaded_ok = 0
        upload_failures: list[str] = []
        url: str | None = None

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
            except AwsCliError as e:
                # AwsCliError already includes actionable guidance
                logger.error(f"  Upload failed: {local.name} -> s3://{cfg.s3_bucket}/{key}")
                logger.error(f"  {str(e)}")
                return (False, f"{local.name} -> s3://{cfg.s3_bucket}/{key}: {str(e).split(chr(10))[0]}")
            except Exception as e:
                error_type = type(e).__name__
                logger.error(f"  Upload failed: {local.name} -> s3://{cfg.s3_bucket}/{key}: {error_type}: {e}")
                return (False, f"{local.name} -> s3://{cfg.s3_bucket}/{key}: {error_type}: {e}")

        # Upload loading page and generate QR code early
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
            raise PipelineError(
                f"Failed to publish gallery link to S3.\n"
                f"  Failed uploads: {len(upload_failures)}\n"
                f"  This prevents sharing the gallery URL.\n"
                f"  Common causes:\n"
                f"    - AWS credentials expired or invalid (run: aws sts get-caller-identity)\n"
                f"    - Insufficient S3 permissions (need s3:PutObject)\n"
                f"    - Network connectivity issues\n"
                f"  See log for detailed error messages."
            )

        # Presign the (loading) index now so we can share immediately.
        logger.info(f"Generating presigned share URL for gallery...")
        url = s3_presign(
            bucket=cfg.s3_bucket,
            key=s3_index_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        share_txt.write_text(url + os.linesep, encoding="utf-8")
        logger.info(f"Share URL (available immediately; expires in {cfg.presign_expiry_seconds}s): {url}")

        # QR code: write a PNG into the session folder and print an ASCII QR in logs.
        qr_png = None
        try:
            qr_png = session_dir / "share-qr.png"
            write_qr_png(data=url, out_path=qr_png)
            logger.info(f"QR code written: {qr_png}")
            logger.info("\n" + render_qr_ascii(url))
            # Verify the QR code file is readable before proceeding
            # This ensures the e-ink display can load it immediately
            if not qr_png.exists() or qr_png.stat().st_size == 0:
                logger.warning(f"QR code file {qr_png} appears to be empty or missing after write")
                qr_png = None
        except QrError as e:
            logger.warning(str(e))

        # Update status immediately with URL and QR path so QR code is available in status system right away.
        # This ensures the QR code shows up on the e-ink display as soon as it's generated.
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="ingest",
                    message="Gallery link ready. Processing files…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"discovered": len(all_media), "new": len(new_files), "skipped": skipped},
                    url=url,
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,
                )
            )

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
                    url=url,  # Include URL so QR code remains visible
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
                )
            )
        copied = 0
        total_size = sum(size for (_, _, size) in new_files)
        copied_size = 0
        logger.info(f"Copying {len(new_files)} files ({total_size:,} bytes total) to {originals_dir}...")
        
        # Parallelize file copying (I/O bound operation)
        def _copy_one(item: tuple[Path, str, int]) -> tuple[bool, int, Path, str]:
            src, sha, size = item
            rel = _safe_rel_under(dcim_dir, src)
            dst = originals_dir / "DCIM" / rel
            
            try:
                # Hash is already computed (size-based pre-filtering disabled)
                copied_file = _copy2_ignore_existing(src, dst)
                return (copied_file, size if copied_file else 0, src, sha)
            except (OSError, IOError) as e:
                error_code = getattr(e, 'errno', None)
                error_msg = str(e)
                # Check if this is a device removal error
                if error_code == 19 or "No such device" in error_msg or "no such device" in error_msg:  # ENODEV
                    raise PipelineError(
                        f"SD card was removed during copying: {src}\n"
                        f"  The device became inaccessible while copying files.\n"
                        f"  This usually means the SD card was physically removed or unmounted.\n"
                        f"  Files already copied have been saved.\n"
                        f"  Try: Re-insert the SD card and run again. Already-copied files will be skipped."
                    ) from e
                elif error_code in (5, 13) or "Input/output error" in error_msg:  # EIO or EACCES
                    raise PipelineError(
                        f"SD card became inaccessible during copying: {src}\n"
                        f"  Error: {error_msg}\n"
                        f"  The device may have been removed or the filesystem may be corrupted.\n"
                        f"  Files already copied have been saved.\n"
                        f"  Try: Re-insert the SD card and check filesystem health."
                    ) from e
                else:
                    # Re-raise other errors
                    raise
        
        copy_workers = min(4, max(1, cfg.process_workers))  # Use fewer workers for copying
        db_inserts: list[tuple[str, int, str]] = []  # (sha, size, source_hint)
        
        try:
            with ThreadPoolExecutor(max_workers=copy_workers) as ex:
                futures = {ex.submit(_copy_one, item): item for item in new_files}
                for i, fut in enumerate(as_completed(futures), 1):
                    try:
                        item = futures[fut]
                        was_copied, file_size, src, sha = fut.result()
                        if was_copied:
                            copied += 1
                            copied_size += file_size
                            logger.info(f"  Copied [{i}/{len(new_files)}]: {src.name} -> {originals_dir / 'DCIM' / _safe_rel_under(dcim_dir, src)} ({file_size:,} bytes)")
                        else:
                            logger.debug(f"  Skipped (already exists at destination): {src.name}")
                        # Always mark as ingested in database (even if already exists at destination,
                        # so we can deduplicate by hash in future runs)
                        db_inserts.append((sha, item[2], str(src)))
                    except PipelineError:
                        # Device removal detected - re-raise to stop copying
                        raise
                    except Exception as e:
                        # Unexpected error during copy - log and continue with other files
                        item = futures[fut]
                        logger.error(f"  Copy failed (unexpected error): {item[0].name}: {e}")
                        # Don't mark as ingested if copy failed
                        continue
        except PipelineError:
            # Device removal - commit what we have so far and re-raise
            if db_inserts:
                logger.warning(f"Device removed during copy - marking {len(db_inserts)} already-copied files in DB...")
                for sha, size, source_hint in db_inserts:
                    _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=source_hint)
                conn.commit()
            raise
        
        # All files are already hashed (no deferred hashing)
        new_files_with_hashes: list[tuple[Path, str, int]] = new_files
        
        # Batch insert into database (more efficient than one-by-one)
        logger.debug(f"Marking {len(db_inserts)} files as ingested in database...")
        for sha, size, source_hint in db_inserts:
            _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=source_hint)
        conn.commit()
        logger.info(f"Ingested originals: {copied} files copied ({copied_size:,} bytes), {len(db_inserts)} marked in DB -> {originals_dir}")

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
                    url=url,  # Include URL so QR code remains visible
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
                        url=url,  # Include URL so QR code remains visible
                        qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
                    )
                )
            with ThreadPoolExecutor(max_workers=max(1, cfg.process_workers)) as ex:
                futures = [ex.submit(_process_one, t) for t in proc_tasks]
                last_ui = time.time()
                for fut in as_completed(futures):
                    try:
                        rel_posix, sort_ts, title, subtitle = fut.result()
                        thumb_href = f"derived/thumbs/{rel_posix}"
                        share_href = f"derived/share/{rel_posix}"
                        gallery_items_local.append((thumb_href, share_href, title, subtitle, sort_ts))
                        processed += 1
                        logger.debug(f"Processed [{processed}/{len(proc_tasks)}]: {rel_posix}")
                    except Exception as e:
                        # Handle processing errors for individual files gracefully
                        # Don't fail the entire pipeline if one file is corrupted
                        logger.warning(f"Failed to process one image file (skipping): {e}")
                        continue
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
                                url=url,  # Include URL so QR code remains visible
                                qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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

        # Upload photos (retry-tolerant) with per-key upload dedupe (idempotent if re-run)
        # Note: Loading page and QR code were already uploaded/generated earlier after session creation.
        if status is not None:
            status.write(
                Status(
                    state="running",
                    step="upload",
                    message="Uploading photos to S3…",
                    session_id=session_id,
                    volume=str(volume_path),
                    counts={"uploaded_done": uploaded_ok, "uploaded_total": 0},
                    url=url,
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,
                )
            )
        # Note: prefix, uploaded_ok, upload_failures, _upload_one, and url are already defined earlier
        # (after session creation, when loading page was uploaded and QR code was generated).
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
            # uploaded_ok already includes early uploads (status.json and loading index.html)
            # The total count should include all uploads: the 2 early ones + the file uploads
            # Note: uploaded_ok may be 0, 1, or 2 depending on whether early uploads succeeded,
            # but the total should always include both early uploads in the count
            EARLY_UPLOADS_COUNT = 2  # status.json and loading index.html
            upload_total_with_early = len(upload_tasks) + EARLY_UPLOADS_COUNT
            if status is not None:
                status.write(
                    Status(
                        state="running",
                        step="upload",
                        message="Uploading to S3…",
                        session_id=session_id,
                        volume=str(volume_path),
                        counts={"uploaded_done": uploaded_ok, "uploaded_total": upload_total_with_early},
                        url=url,  # Include URL so QR code remains visible
                        qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
                        logger.info(f"Uploaded [{uploaded_ok}/{upload_total_with_early}]: {task[0].name} -> {task[1]}")
                    if err:
                        upload_failures.append(err)
                        logger.error(f"Upload failed [{uploaded_ok}/{upload_total_with_early}]: {task[0].name} -> {task[1]}: {err}")

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
                                counts={"uploaded_done": uploaded_ok, "uploaded_total": upload_total_with_early},
                                url=url,  # Include URL so QR code remains visible
                                qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
            total_attempted = len(upload_tasks)
            success_rate = (uploaded_ok / total_attempted * 100) if total_attempted > 0 else 0
            raise PipelineError(
                f"Upload failed for {len(upload_failures)} of {total_attempted} objects ({success_rate:.1f}% succeeded).\n"
                f"  Common causes:\n"
                f"    - Network connectivity issues (check internet connection)\n"
                f"    - AWS credentials expired (run: aws sts get-caller-identity)\n"
                f"    - Insufficient S3 permissions (need s3:PutObject for bucket: {cfg.s3_bucket})\n"
                f"    - S3 bucket doesn't exist or is in a different region\n"
                f"  Tip: You can retry by running the same command again (already uploaded files will be skipped).\n"
                f"  See log for detailed error messages per file."
            )

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
                    url=url,  # Include URL so QR code remains visible
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
                                url=url,  # Include URL so QR code remains visible
                                qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
                    url=url,  # Include URL so QR code remains visible
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,  # Include QR path so QR code remains visible
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
            raise PipelineError(
                f"Failed to upload final gallery (index.html) to S3.\n"
                f"  The gallery page was generated locally but couldn't be uploaded.\n"
                f"  This means images may be uploaded but the gallery won't be accessible via the share link.\n"
                f"  Common causes:\n"
                f"    - Network connectivity issues\n"
                f"    - AWS credentials or permissions issue\n"
                f"    - S3 bucket access problem\n"
                f"  Tip: Check AWS credentials with: aws sts get-caller-identity\n"
                f"  See log for detailed error message."
            )

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
                    message="Complete. Remove SD card when ready.",
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
                    qr_path=str(qr_png) if qr_png and qr_png.exists() and qr_png.stat().st_size > 0 else None,
                )
            )

        return sp, url
    finally:
        conn.close()


