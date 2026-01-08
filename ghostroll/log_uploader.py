"""Robust log uploader that ensures logs are uploaded even if the application crashes."""

from __future__ import annotations

import atexit
import logging
import signal
import threading
import time
from pathlib import Path

from .aws_boto3 import s3_upload_file


logger = logging.getLogger("ghostroll")


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
                        handler.flush()
                    # Also flush root handlers
                    for handler in logging.root.handlers:
                        handler.flush()
                
                # Upload the log file
                uploaded, err = s3_upload_file(
                    local_path=self.log_file,
                    bucket=self.s3_bucket,
                    key=self.s3_key,
                )
                
                if uploaded:
                    self._last_upload_time = time.time()
                    self._upload_count += 1
                    return True
                else:
                    logger.debug(f"Log upload failed: {err}")
                    return False
            except Exception as e:
                logger.debug(f"Log upload exception: {e}")
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
    
    def _signal_handler(self, signum, frame):
        """Handle signals (SIGTERM, SIGINT, etc.) to ensure log upload."""
        signal_name = signal.Signals(signum).name
        logger.warning(f"Received signal {signal_name}, uploading log before exit...")
        
        # Stop periodic uploads
        self.stop()
        
        # Force upload the log
        self._upload_log(force_flush=True)
        
        # Re-raise the signal to allow normal cleanup
        signal.signal(signum, signal.SIG_DFL)
        signal.raise_signal(signum)
    
    def _atexit_handler(self):
        """Handle normal program exit to ensure log upload."""
        logger.debug("Program exiting, uploading log...")
        self.stop()
        self._upload_log(force_flush=True)
    
    def register_handlers(self):
        """Register signal and atexit handlers for automatic log upload on exit/crash."""
        if self._registered_handlers:
            return
        
        # Register signal handlers for graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                # Save existing handler if any
                old_handler = signal.signal(sig, self._signal_handler)
                logger.debug(f"Registered signal handler for {signal.Signals(sig).name}")
            except (ValueError, OSError) as e:
                # Some signals may not be available on all platforms
                logger.debug(f"Could not register signal handler for {signal.Signals(sig).name}: {e}")
        
        # Register atexit handler for normal exits
        atexit.register(self._atexit_handler)
        logger.debug("Registered atexit handler for log upload")
        
        self._registered_handlers = True
    
    def start(self):
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

