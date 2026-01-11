"""Robust log uploader that ensures logs are uploaded even if the application crashes."""

from __future__ import annotations

import atexit
import logging
import signal
import threading
import time
import weakref
from pathlib import Path

from .aws_boto3 import s3_upload_file, AwsBoto3Error


logger = logging.getLogger("ghostroll")

_UPLOADERS: "weakref.WeakSet[LogUploader]" = weakref.WeakSet()
_HANDLERS_INSTALLED = False
_HANDLERS_LOCK = threading.Lock()


def _upload_all(*, force_flush: bool) -> None:
    # Best-effort: never raise from here.
    for uploader in list(_UPLOADERS):
        try:
            uploader.stop()
            uploader._upload_log(force_flush=force_flush)
        except Exception:
            pass


def _global_signal_handler(signum, frame):
    signal_name = signal.Signals(signum).name
    logger.warning(f"Received signal {signal_name}, uploading logs before exit...")
    _upload_all(force_flush=True)
    # Re-raise the signal to allow normal cleanup
    signal.signal(signum, signal.SIG_DFL)
    signal.raise_signal(signum)


def _global_atexit_handler():
    # Logging may already be partially shut down at interpreter exit; avoid emitting logs here.
    try:
        _upload_all(force_flush=True)
    except Exception:
        pass


def _ensure_global_handlers_installed() -> None:
    global _HANDLERS_INSTALLED
    with _HANDLERS_LOCK:
        if _HANDLERS_INSTALLED:
            return
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _global_signal_handler)
                logger.debug(f"Registered global signal handler for {signal.Signals(sig).name}")
            except (ValueError, OSError) as e:
                logger.debug(f"Could not register global signal handler for {signal.Signals(sig).name}: {e}")
        atexit.register(_global_atexit_handler)
        logger.debug("Registered global atexit handler for log upload")
        _HANDLERS_INSTALLED = True


class LogUploader:
    """Manages automatic and bulletproof log uploads to S3."""
    
    def __init__(
        self,
        *,
        log_file: Path,
        s3_bucket: str,
        s3_key: str,
        upload_interval: float = 30.0,  # Upload every 30 seconds during processing
    ):
        """
        Initialize log uploader.
        
        Args:
            log_file: Path to the local log file
            s3_bucket: S3 bucket name
            s3_key: S3 key (full path) for the log file
            upload_interval: How often to upload logs during processing (seconds)
        """
        self.log_file = log_file
        self.s3_bucket = s3_bucket
        self.s3_key = s3_key
        self.upload_interval = upload_interval
        self._upload_lock = threading.Lock()
        self._upload_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._registered_handlers = False
        self._last_upload_time = 0.0
        self._upload_count = 0
    
    def _upload_log(self, *, force_flush: bool = False) -> bool:
        """
        Upload log file to S3.
        
        Args:
            force_flush: If True, flush all log handlers before upload
        
        Returns:
            True if upload succeeded, False otherwise
        """
        if not self.log_file.exists():
            return False
        
        with self._upload_lock:
            try:
                # Flush all log handlers to ensure log file is complete
                if force_flush:
                    root_logger = logging.getLogger("ghostroll")
                    for handler in root_logger.handlers:
                        try:
                            handler.flush()
                        except Exception:
                            pass
                    # Also flush root handlers
                    for handler in logging.root.handlers:
                        try:
                            handler.flush()
                        except Exception:
                            pass
                
                # Upload the log file
                # s3_upload_file returns None on success, raises AwsBoto3Error on failure
                try:
                    s3_upload_file(
                        local_path=self.log_file,
                        bucket=self.s3_bucket,
                        key=self.s3_key,
                    )
                    # Upload succeeded
                    self._last_upload_time = time.time()
                    self._upload_count += 1
                    return True
                except AwsBoto3Error as e:
                    try:
                        logger.debug(f"Log upload failed: {e}")
                    except Exception:
                        pass
                    return False
            except Exception as e:
                try:
                    logger.debug(f"Log upload exception: {e}")
                except Exception:
                    pass
                return False
    
    def _periodic_upload_worker(self):
        """Background thread that periodically uploads logs during processing."""
        while not self._stop_event.is_set():
            # Wait for the interval, or until stop is signaled
            if self._stop_event.wait(timeout=self.upload_interval):
                # Stop was signaled, do one final upload
                break
            
            # Periodic upload during processing
            if self.log_file.exists() and self.log_file.stat().st_size > 0:
                self._upload_log(force_flush=False)
        
        # Final upload when stopping
        self._upload_log(force_flush=True)
    
    def register_handlers(self):
        """Register global signal and atexit handlers for automatic log upload on exit/crash."""
        if self._registered_handlers:
            return

        _UPLOADERS.add(self)
        _ensure_global_handlers_installed()
        self._registered_handlers = True
    
    def start(self, *, upload_immediately: bool = True):
        """Start periodic log uploads in background thread."""
        if self._upload_thread is not None and self._upload_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._upload_thread = threading.Thread(
            target=self._periodic_upload_worker,
            daemon=True,  # Daemon thread so it doesn't prevent program exit
            name="LogUploader",
        )
        self._upload_thread.start()
        logger.debug(f"Started periodic log uploader (interval: {self.upload_interval}s)")
        if upload_immediately:
            # Don't wait for the first interval; get something up to S3 right away.
            self._upload_log(force_flush=True)
    
    def stop(self):
        """Stop periodic log uploads."""
        if self._upload_thread is None:
            return
        
        self._stop_event.set()
        if self._upload_thread.is_alive():
            # Wait for thread to finish (with timeout)
            self._upload_thread.join(timeout=5.0)
            if self._upload_thread.is_alive():
                logger.warning("Log uploader thread did not stop within timeout")
    
    def upload_now(self, *, force_flush: bool = True) -> bool:
        """
        Immediately upload the log file.
        
        Args:
            force_flush: If True, flush all log handlers before upload
        
        Returns:
            True if upload succeeded, False otherwise
        """
        return self._upload_log(force_flush=force_flush)
    
    def get_stats(self) -> dict:
        """Get upload statistics."""
        return {
            "upload_count": self._upload_count,
            "last_upload_time": self._last_upload_time,
            "is_running": self._upload_thread is not None and self._upload_thread.is_alive(),
        }


def ensure_log_upload(
    *,
    log_file: Path,
    s3_bucket: str,
    s3_key: str,
    upload_interval: float = 30.0,
) -> LogUploader:
    """
    Create and configure a log uploader for a session.
    
    This sets up automatic periodic uploads and ensures the log is uploaded
    even if the application crashes or is interrupted.
    
    Args:
        log_file: Path to the local log file
        s3_bucket: S3 bucket name
        s3_key: S3 key (full path) for the log file
        upload_interval: How often to upload logs during processing (seconds)
    
    Returns:
        LogUploader instance (call start() to begin periodic uploads)
    """
    uploader = LogUploader(
        log_file=log_file,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        upload_interval=upload_interval,
    )
    
    # Register handlers for automatic upload on exit/crash
    uploader.register_handlers()
    
    return uploader


def recover_session_logs(
    *,
    sessions_dir: Path,
    s3_bucket: str,
    s3_prefix_root: str,
    max_sessions: int = 20,
    logger: logging.Logger | None = None,
) -> int:
    """
    Best-effort startup recovery: upload session `ghostroll.log` files that exist locally.

    This covers cases where a prior run died abruptly (no atexit/signal handling) but the
    device stayed on and the logfile was written to disk.
    """
    try:
        if not sessions_dir.exists() or not sessions_dir.is_dir():
            return 0
    except Exception:
        return 0

    try:
        # Most-recent-first so we cover the latest crash quickly.
        session_dirs = [p for p in sessions_dir.iterdir() if p.is_dir()]
        session_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return 0

    uploaded = 0
    prefix_root = s3_prefix_root or ""

    for session_dir in session_dirs[:max_sessions]:
        session_id = session_dir.name
        log_file = session_dir / "ghostroll.log"
        try:
            if not log_file.exists() or log_file.stat().st_size <= 0:
                continue
        except Exception:
            continue

        prefix = f"{prefix_root}{session_id}".rstrip("/")
        log_key = f"{prefix}/logs/ghostroll.log"

        try:
            s3_upload_file(local_path=log_file, bucket=s3_bucket, key=log_key, retries=3)
            uploaded += 1
            if logger:
                logger.info(f"Recovered session log upload: s3://{s3_bucket}/{log_key}")
        except AwsBoto3Error as e:
            if logger:
                logger.warning(f"Failed to recover-upload {log_file} -> s3://{s3_bucket}/{log_key}: {e}")
        except Exception as e:
            if logger:
                logger.warning(f"Failed to recover-upload {log_file} -> s3://{s3_bucket}/{log_key}: {type(e).__name__}: {e}")

    return uploaded

