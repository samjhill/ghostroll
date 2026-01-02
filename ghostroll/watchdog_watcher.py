from __future__ import annotations

import logging
import subprocess
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
        
        # Verify it's actually a mount (not just a directory or automount) before calling callback
        # This prevents false positives from existing directories and automount placeholders
        import platform
        system = platform.system().lower()
        
        if system == "linux":
            try:
                with open("/proc/mounts", "r") as f:
                    mounts_text = f.read()
                    target = str(event_path).replace(" ", "\\040")
                    
                    # Check if it's in /proc/mounts
                    if target not in mounts_text:
                        logger.warning(f"Watchdog: {event_path} created but not in /proc/mounts - ignoring (not a real mount)")
                        return
                    
                    # Check if it's an automount (autofs filesystem or systemd-1 source)
                    for line in mounts_text.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1] == target:
                            src = parts[0] if len(parts) > 0 else ""
                            fstype = parts[2] if len(parts) > 2 else ""
                            
                            # Reject autofs filesystem type (automount placeholder)
                            if fstype == "autofs":
                                logger.warning(f"Watchdog: {event_path} is autofs - ignoring (automount placeholder)")
                                return
                            
                            # Reject systemd-1 or autofs sources (automount services)
                            if src.startswith("systemd-1") or "autofs" in src.lower():
                                logger.warning(f"Watchdog: {event_path} has automount source {src} - ignoring")
                                return
                            
                            # For /dev/ devices, verify the device file exists (catch stale mounts)
                            if src.startswith("/dev/"):
                                try:
                                    from pathlib import Path
                                    if not Path(src).exists():
                                        logger.warning(f"Watchdog: {event_path} device {src} does not exist - ignoring (stale mount)")
                                        return
                                except Exception:
                                    pass  # If we can't check, assume it's valid
                            
                            # It's a real mount - proceed
                            break
            except Exception as e:
                logger.debug(f"Error checking /proc/mounts: {e}")
                # If we can't check, proceed anyway (better to have false positive than miss real mount)
        elif system == "darwin":
            # On macOS, /Volumes is always mounts, so we can trust it
            # For other paths, check using mount command
            vol_str = str(event_path)
            if not vol_str.startswith("/Volumes/"):
                try:
                    result = subprocess.run(
                        ["mount"], capture_output=True, text=True, timeout=2
                    )
                    if result.returncode == 0 and vol_str not in result.stdout:
                        logger.warning(f"Watchdog: {event_path} created but not in mount output - ignoring (not a real mount)")
                        return
                except Exception:
                    # If we can't check, proceed anyway
                    pass
        
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

