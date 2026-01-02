from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEventHandler = object  # type: ignore
    Observer = object  # type: ignore

logger = logging.getLogger("ghostroll.watchdog_watcher")


class MountEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler that detects when directories are created/deleted
    in mount root directories (like /Volumes, /media, /mnt).
    """
    
    def __init__(self, mount_roots: list[Path], label: str, callback: Callable[[Path], None]):
        """
        Args:
            mount_roots: List of mount root directories to watch (e.g., [/Volumes, /media])
            label: Volume label to match (e.g., "auto-import")
            callback: Function to call when a matching volume is detected
        """
        super().__init__()
        self.mount_roots = mount_roots
        self.label = label
        self.callback = callback
        self._last_event_time: dict[str, float] = {}
        self._debounce_seconds = 0.5  # Debounce rapid events
    
    def _matches_label(self, name: str) -> bool:
        """Check if a directory name matches our target label."""
        return name == self.label or name.startswith(self.label + " ")
    
    def _should_process(self, event_path: Path) -> bool:
        """Check if we should process this event (debounce and label matching)."""
        event_str = str(event_path)
        now = time.time()
        
        # Debounce: ignore events that happen too quickly after the last one
        if event_str in self._last_event_time:
            if now - self._last_event_time[event_str] < self._debounce_seconds:
                return False
        
        self._last_event_time[event_str] = now
        
        # Check if the directory name matches our label
        if not self._matches_label(event_path.name):
            return False
        
        return True
    
    def on_created(self, event):
        """Called when a directory is created (SD card mounted)."""
        if not event.is_directory:
            return
        
        event_path = Path(event.src_path)
        logger.debug(f"Directory created event: {event_path}")
        
        if not self._should_process(event_path):
            return
        
        logger.info(f"Potential SD card mount detected: {event_path}")
        # Give the filesystem a moment to fully mount
        time.sleep(0.2)
        self.callback(event_path)
    
    def on_deleted(self, event):
        """Called when a directory is deleted (SD card unmounted)."""
        if not event.is_directory:
            return
        
        event_path = Path(event.src_path)
        logger.debug(f"Directory deleted event: {event_path}")
        
        if self._matches_label(event_path.name):
            logger.info(f"SD card unmount detected: {event_path}")


class WatchdogWatcher:
    """
    Watchdog-based filesystem watcher for SD card mount detection.
    
    This provides real-time detection of mount/unmount events instead of polling.
    Falls back to polling if Watchdog is not available.
    """
    
    def __init__(self, mount_roots: list[Path], label: str, callback: Callable[[Path], None]):
        """
        Args:
            mount_roots: List of mount root directories to watch
            label: Volume label to match
            callback: Function to call when a matching volume is detected
        """
        self.mount_roots = mount_roots
        self.label = label
        self.callback = callback
        self.observer: Observer | None = None
        self.running = False
    
    def start(self):
        """Start watching for mount events."""
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available, falling back to polling mode")
            return False
        
        if self.running:
            logger.warning("Watcher is already running")
            return False
        
        try:
            self.observer = Observer()
            handler = MountEventHandler(self.mount_roots, self.label, self.callback)
            
            # Watch each mount root
            for mount_root in self.mount_roots:
                if mount_root.exists() and mount_root.is_dir():
                    logger.info(f"Watching mount root: {mount_root}")
                    self.observer.schedule(handler, str(mount_root), recursive=False)
                else:
                    logger.debug(f"Skipping non-existent mount root: {mount_root}")
            
            self.observer.start()
            self.running = True
            logger.info("Watchdog watcher started")
            return True
        except Exception as e:
            logger.error(f"Failed to start Watchdog watcher: {e}")
            return False
    
    def stop(self):
        """Stop watching for mount events."""
        if not self.running or self.observer is None:
            return
        
        try:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.running = False
            logger.info("Watchdog watcher stopped")
        except Exception as e:
            logger.error(f"Error stopping Watchdog watcher: {e}")
    
    def is_available(self) -> bool:
        """Check if Watchdog is available."""
        return WATCHDOG_AVAILABLE

