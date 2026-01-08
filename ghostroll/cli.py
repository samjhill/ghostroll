from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

from .config import load_config
from .doctor import format_results, run_doctor
from .logging_utils import setup_logging
from .pipeline import PipelineError, run_pipeline
from .status import Status, StatusWriter, get_hostname, get_ip_address
from .volume_watch import find_candidate_mounts, pick_mount_with_dcim
from .watchdog_watcher import WatchdogWatcher
from .web import GhostRollWebServer


def _is_mounted(where: Path) -> bool:
    """
    Returns True if `where` is currently a mountpoint (uses findmnt on Linux).
    Important: does NOT touch the filesystem under `where`, so it won't trigger systemd automount.
    
    Also checks that it's a real device mount (not just an automount placeholder).
    Uses findmnt for simpler, more reliable detection.
    """
    system = platform.system().lower()
    vol_str = str(where)
    
    if system == "darwin":
        if vol_str.startswith("/Volumes/"):
            return True
        try:
            result = subprocess.run(
                ["mount"], capture_output=True, text=True, timeout=2
            )
            return vol_str in result.stdout
        except Exception:
            return False
    
    if system == "linux":
        # /media and /run/media are typically always mounts
        if vol_str.startswith("/media/") or vol_str.startswith("/run/media/"):
            return True
        
        # Use findmnt (simpler than parsing /proc/mounts)
        try:
            result = subprocess.run(
                ["findmnt", "-n", "-o", "FSTYPE,SOURCE", vol_str],
                capture_output=True,
                text=True,
                timeout=2
            )
            
            if result.returncode != 0:
                return False
            
            output = result.stdout.strip()
            if not output:
                return False
            
            # Parse: "FSTYPE SOURCE"
            parts = output.split(None, 1)
            if len(parts) < 1:
                return False
            
            fstype = parts[0]
            source = parts[1] if len(parts) > 1 else ""
            
            # Reject autofs
            if fstype == "autofs":
                return False
            
            # Reject systemd-1 or autofs sources
            if source.startswith("systemd-1") or "autofs" in source.lower():
                return False
            
            # For /dev/ devices, verify device exists
            if source.startswith("/dev/"):
                if not Path(source).exists():
                    return False
            
            return True
            
        except FileNotFoundError:
            # findmnt not available, fall back to /proc/mounts
            try:
                mounts_text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
                target = vol_str.replace(" ", "\\040")
                for line in mounts_text.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == target:
                        fstype = parts[2] if len(parts) > 2 else ""
                        if fstype == "autofs":
                            return False
                        return True
                return False
            except Exception:
                return False
        except Exception:
            return False
    
    return False


def _can_write_to_volume(vol: Path) -> bool:
    """
    Check if a volume is actually accessible by attempting to write and read a temporary file.
    This is more definitive than checking directory listings - if we can't write, the device is gone.
    Returns True if the volume is accessible and writable, False otherwise.
    """
    test_file = None
    try:
        # Try to create a temporary file in the volume root
        # Use a name that's unlikely to conflict
        test_file = vol / ".ghostroll_test_write.tmp"
        
        # Write test data
        test_data = b"test"
        test_file.write_bytes(test_data)
        
        # Try to read it back
        read_data = test_file.read_bytes()
        if read_data != test_data:
            return False
        
        # Clean up
        test_file.unlink()
        return True
    except (OSError, IOError, PermissionError):
        # Any error means the volume is not accessible
        # Clean up if file was created (handle cleanup failures gracefully)
        if test_file is not None:
            try:
                if test_file.exists():
                    test_file.unlink()
            except Exception:
                # Ignore cleanup errors - device might be gone
                pass
        return False
    except Exception:
        # Unexpected error - assume not accessible
        # Clean up if file was created (handle cleanup failures gracefully)
        if test_file is not None:
            try:
                if test_file.exists():
                    test_file.unlink()
            except Exception:
                # Ignore cleanup errors - device might be gone
                pass
        return False


def _try_unmount(where: Path, logger) -> bool:
    """
    Try to unmount a mount point. Returns True if successful or already unmounted,
    False if unmount failed for other reasons.
    
    Uses platform-appropriate unmount command:
    - macOS: diskutil unmount (or umount as fallback)
    - Linux: umount
    """
    try:
        # Check if it's actually mounted first
        if not _is_mounted(where):
            logger.debug(f"Mount point {where} is not mounted, skipping unmount")
            return True
        
        # Try to unmount it using platform-appropriate command
        logger.debug(f"Attempting to unmount {where}")
        system = platform.system().lower()
        
        if system == "darwin":
            # On macOS, prefer diskutil unmount for volumes
            # diskutil unmount doesn't require sudo for user-mounted volumes
            result = subprocess.run(
                ["diskutil", "unmount", str(where)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.debug(f"Successfully unmounted {where} using diskutil")
                return True
            # Fallback to umount if diskutil fails
            logger.debug(f"diskutil unmount failed, trying umount: {result.stderr}")
            result = subprocess.run(
                ["umount", str(where)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        else:
            # Linux and other Unix-like systems
            result = subprocess.run(
                ["umount", str(where)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        
        if result.returncode == 0:
            logger.debug(f"Successfully unmounted {where}")
            return True
        else:
            # Check if error is "not mounted" (already unmounted)
            error_msg = (result.stderr or "").lower()
            if "not mounted" in error_msg or "no such file or directory" in error_msg or "not currently mounted" in error_msg:
                logger.debug(f"Mount point {where} was already unmounted")
                return True
            logger.debug(f"Unmount failed for {where}: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.debug(f"Unmount timed out for {where}")
        return False
    except Exception as e:
        logger.debug(f"Unmount error for {where}: {e}")
        return False


def _is_mount_accessible(where: Path) -> bool:
    """
    Check if a mountpoint is actually accessible (not just in mount table).
    This catches cases where the mount is "lazy unmounted" - still in /proc/mounts
    but the device is actually gone.
    
    Uses a lightweight check that will fail if the underlying device is removed.
    """
    try:
        # Try to stat the mountpoint itself (not its contents, to avoid triggering automount)
        # If the mount is stale, this will fail with ENODEV or EIO
        stat_result = where.stat()
        # Check if it's actually a directory (mountpoints should be directories)
        import stat
        if not stat.S_ISDIR(stat_result.st_mode):
            return False
        
        # Try to access the directory in a way that will fail if device is gone
        # We use a very lightweight check: try to get one directory entry
        # This will raise OSError with ENODEV/EIO if the device is gone
        try:
            # Use next() on iterator - very lightweight, doesn't read all entries
            next(where.iterdir(), None)
        except (OSError, PermissionError):
            # OSError with ENODEV/EIO means device is gone
            # PermissionError might be fine, but let's be conservative and assume it's gone
            return False
        except StopIteration:
            # Empty directory is fine
            pass
        
        return True
    except (OSError, PermissionError) as e:
        # Can't stat or access - mount is likely gone
        # Common errors: ENODEV (No such device), EIO (Input/output error)
        return False


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sd-label", default=None, help="SD card volume label to watch (default: auto-import)")
    p.add_argument("--base-dir", default=None, help="Base output directory (default: ~/ghostroll)")
    p.add_argument("--db-path", default=None, help="SQLite DB path for dedupe (default: ~/.ghostroll/ghostroll.db)")
    p.add_argument("--s3-bucket", default=None, help="S3 bucket name (default: photo-ingest-project)")
    p.add_argument("--s3-prefix-root", default=None, help="S3 prefix root (default: sessions/)")
    p.add_argument("--presign-expiry-seconds", type=int, default=None, help="Presign expiry seconds (default: 604800)")
    p.add_argument(
        "--mount-roots",
        default="/Volumes,/media,/run/media,/mnt",
        help="Comma-separated mount roots to scan (default: /Volumes,/media,/run/media,/mnt).",
    )
    p.add_argument(
        "--status-path",
        default=None,
        help="Where to write status JSON (default: ~/ghostroll/status.json)",
    )
    p.add_argument(
        "--status-image-path",
        default=None,
        help="Where to write status PNG for e-ink (default: ~/ghostroll/status.png)",
    )
    p.add_argument(
        "--status-image-size",
        default=None,
        help="Status PNG size like 800x480 (default: 800x480)",
    )
    p.add_argument("--quiet", action="store_true", help="Reduce log verbosity (INFO level only, no DEBUG)")


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(
        sd_label=args.sd_label,
        base_output_dir=args.base_dir,
        db_path=args.db_path,
        s3_bucket=args.s3_bucket,
        s3_prefix_root=args.s3_prefix_root,
        presign_expiry_seconds=args.presign_expiry_seconds,
        mount_roots=args.mount_roots,
        status_path=args.status_path,
        status_image_path=args.status_image_path,
        status_image_size=args.status_image_size,
    )

    # Accept either an explicit mounted path (recommended) or a volume label like "auto-import".
    vol_arg = str(args.volume)
    if "/" not in vol_arg and "\\" not in vol_arg:
        # Interpret as label under common mount roots (macOS/Linux), including "auto-import 1" suffixes.
        guessed = pick_mount_with_dcim(cfg.mount_roots, label=vol_arg)
        volume = guessed if guessed is not None else Path(vol_arg).resolve()
    else:
        volume = Path(vol_arg).resolve()
    logger = setup_logging(session_dir=None, verbose=not args.quiet)
    status = StatusWriter(
        json_path=cfg.status_path,
        image_path=cfg.status_image_path,
        image_size=cfg.status_image_size,
    )
    status.write(Status(state="running", step="start", message="Starting run…", volume=str(volume)))
    logger.info(f"Volume: {volume}")
    try:
        sp, url = run_pipeline(
            cfg=cfg,
            volume_path=volume,
            logger=logger,
            status=status,
            always_create_session=args.always_create_session,
            session_id=args.session_id,
        )
        if sp is None:
            logger.info("No new files detected; nothing to do.")
            return 0
        logger.info(f"Session created: {sp.session_dir}")
        if url:
            print(url)
        logger.info(f"Share link saved to: {sp.share_txt}")
        return 0
    except PipelineError as e:
        # PipelineError messages already include actionable guidance
        logger.error(str(e))
        status.write(Status(state="error", step="error", message=str(e).split("\n")[0], volume=str(volume)))
        return 2
    except Exception as e:
        # For unexpected errors, provide general guidance
        error_type = type(e).__name__
        logger.error(f"Unexpected error ({error_type}): {e}")
        logger.error(
            f"  This is an unexpected error. Please report this issue with:\n"
            f"    - The full error message above\n"
            f"    - Your GhostRoll version\n"
            f"    - The command you ran\n"
            f"  Tip: Run 'ghostroll doctor' to check your configuration."
        )
        status.write(
            Status(
                state="error",
                step="error",
                message=f"Unexpected error: {error_type}",
                volume=str(volume),
            )
        )
        return 2


def cmd_watch(args: argparse.Namespace) -> int:
    cfg = load_config(
        sd_label=args.sd_label,
        base_output_dir=args.base_dir,
        db_path=args.db_path,
        s3_bucket=args.s3_bucket,
        s3_prefix_root=args.s3_prefix_root,
        presign_expiry_seconds=args.presign_expiry_seconds,
        poll_seconds=args.poll_seconds,
        mount_roots=args.mount_roots,
        status_path=args.status_path,
        status_image_path=args.status_image_path,
        status_image_size=args.status_image_size,
        web_enabled=args.web_enabled if hasattr(args, "web_enabled") and args.web_enabled is not None else None,
        web_host=args.web_host if hasattr(args, "web_host") else None,
        web_port=args.web_port if hasattr(args, "web_port") else None,
    )
    logger = setup_logging(session_dir=None, verbose=not args.quiet)
    status = StatusWriter(
        json_path=cfg.status_path,
        image_path=cfg.status_image_path,
        image_size=cfg.status_image_size,
    )

    logger.info(
        f"GhostRoll watching for SD volume '{cfg.sd_label}' under: {', '.join([str(p) for p in cfg.mount_roots])}"
    )
    logger.info(f"Polling interval: {cfg.poll_seconds}s")
    logger.info(f"Session directory: {cfg.sessions_dir}")
    logger.info(f"S3 bucket: {cfg.s3_bucket}")
    
    # Start web server if enabled
    logger.info(f"Web interface configuration: enabled={cfg.web_enabled}, host={cfg.web_host}, port={cfg.web_port}")
    web_server = None
    if cfg.web_enabled:
        logger.info(f"Starting web interface on {cfg.web_host}:{cfg.web_port}...")
        web_server = GhostRollWebServer(
            status_path=cfg.status_path,
            sessions_dir=cfg.sessions_dir,
            host=cfg.web_host,
            port=cfg.web_port,
        )
        if web_server.start():
            web_url = web_server.get_url()
            logger.info(f"Web interface enabled: {web_url}")
            logger.info(f"  Status: {web_url}/status.json")
            logger.info(f"  Sessions: {web_url}/sessions")
        else:
            logger.warning(f"Failed to start web server on {cfg.web_host}:{cfg.web_port} (port may be in use)")
            web_server = None
    else:
        logger.debug("Web interface is disabled (GHOSTROLL_WEB_ENABLED not set or false)")
    
    # Try to unmount any stale mounts before starting
    logger.debug("Checking for stale mounts before starting...")
    for root in cfg.mount_roots:
        try:
            cands = find_candidate_mounts([root], label=cfg.sd_label)
            for cand in cands:
                # Try to unmount stale mounts (they might be accessible but stale)
                _try_unmount(cand, logger)
        except Exception:
            # Ignore errors during cleanup
            pass
    
    logger.info("Insert the SD card to begin.")
    status.write(
        Status(
            state="idle",
            step="watch",
            message="Waiting for SD card…",
            hostname=get_hostname(),
            ip=get_ip_address(),
        )
    )

    last_processed_volume: Path | None = None
    card_detected_event = threading.Event()
    detected_volume: Path | None = None
    
    def on_card_detected(vol: Path):
        """Callback when Watchdog detects a potential card mount."""
        nonlocal detected_volume
        logger.info(f"Watchdog detected potential mount: {vol}")
        # Verify it has DCIM before triggering
        dcim_path = vol / "DCIM"
        if dcim_path.exists() and dcim_path.is_dir():
            try:
                list(dcim_path.iterdir())  # Verify accessible
                detected_volume = vol
                card_detected_event.set()
            except Exception:
                logger.debug(f"Mount {vol} detected but DCIM not accessible yet")
    
    # Try to use Watchdog for real-time detection
    watcher = WatchdogWatcher(cfg.mount_roots, cfg.sd_label, on_card_detected)
    use_watchdog = watcher.start()
    
    if use_watchdog:
        logger.info("Using Watchdog for real-time mount detection")
    else:
        logger.info(f"Using polling mode (checking every {cfg.poll_seconds}s)")
    
    try:
        while True:
            # If using Watchdog, wait for event; otherwise poll
            if use_watchdog:
                # Wait for Watchdog event or timeout for periodic check
                if card_detected_event.wait(timeout=cfg.poll_seconds):
                    vol = detected_volume
                    card_detected_event.clear()
                    detected_volume = None
                else:
                    # Timeout - do a normal check anyway (fallback)
                    vol = pick_mount_with_dcim(cfg.mount_roots, label=cfg.sd_label)
            else:
                # Polling mode
                vol = pick_mount_with_dcim(cfg.mount_roots, label=cfg.sd_label)
            
            if vol is None:
                # Reset last processed volume if no card is found
                if last_processed_volume is not None:
                    logger.debug("No card detected, resetting last processed volume")
                    last_processed_volume = None
                cands = find_candidate_mounts(cfg.mount_roots, label=cfg.sd_label)
                if cands:
                    logger.warning(f"Volume detected ({', '.join([str(c) for c in cands])}) but no accessible DCIM directory. Waiting...")
                else:
                    logger.debug(f"No volume with label '{cfg.sd_label}' found. Waiting...")
                time.sleep(cfg.poll_seconds)
                continue

            # Skip if this is the same volume we just processed (prevents infinite loop)
            # Original 0.2.0 behavior: always skip if same volume, wait for removal
            if last_processed_volume is not None and str(vol) == str(last_processed_volume):
                logger.debug(f"Skipping {vol} - already processed. Waiting for card removal...")
                time.sleep(cfg.poll_seconds)
                continue

            logger.info(f"Detected camera volume: {vol}")
            logger.debug(f"Volume path: {vol}")
            logger.debug(f"DCIM directory: {vol / 'DCIM'}")
            status.write(Status(state="running", step="detected", message="SD card detected.", volume=str(vol)))
            
            # After remount, filesystem may need time to sync directory entries
            # Add a short delay to ensure all files are visible before scanning
            logger.debug("Waiting for filesystem to sync after mount...")
            time.sleep(1.0)  # 1 second delay to allow filesystem to sync
            
            rc = cmd_run(
                argparse.Namespace(
                    sd_label=cfg.sd_label,
                    base_dir=str(cfg.base_output_dir),
                    db_path=str(cfg.db_path),
                    s3_bucket=cfg.s3_bucket,
                    s3_prefix_root=cfg.s3_prefix_root,
                    presign_expiry_seconds=cfg.presign_expiry_seconds,
                    mount_roots=args.mount_roots,
                    status_path=args.status_path,
                    status_image_path=args.status_image_path,
                    status_image_size=args.status_image_size,
                    quiet=args.quiet,
                    volume=str(vol),
                    always_create_session=args.always_create_session,
                    session_id=None,
                )
            )
            if rc != 0:
                logger.error(f"Run failed with exit code {rc}. Waiting for card removal before retrying.")
            else:
                logger.info("✅ Image offloading complete. You may remove the SD card now.")
                # Update status to show completion message on e-ink
                status.write(
                    Status(
                        state="done",
                        step="done",
                        message="Complete. Remove SD card now.",
                        hostname=get_hostname(),
                        ip=get_ip_address(),
                    )
                )
            
            # Mark this volume as processed to prevent immediate re-processing
            # This matches 0.2.0 behavior - always mark as processed regardless of success/failure
            last_processed_volume = vol
            logger.debug(f"Marked {vol} as processed")
            
            # Unmount the volume after processing (whether successful or not)
            logger.debug(f"Unmounting {vol} after processing")
            _try_unmount(vol, logger)
            
            logger.info("Waiting for card removal before checking for next card...")
            logger.debug(f"Last detected volume: {vol}")
            
            while True:
                # Check if we can still write to the volume - this is the definitive test
                # If we can't write, the card is definitely gone (even if mount point exists)
                try:
                    if not _can_write_to_volume(vol):
                        logger.info(f"Removal detected: cannot write to {vol} (card removed)")
                        break
                except Exception as e:
                    # If the write test itself fails with an exception, treat it as removal
                    logger.info(f"Removal detected: write test failed with exception: {e}")
                    break
                
                # Also check if a different card was inserted
                current_vol = pick_mount_with_dcim(cfg.mount_roots, label=cfg.sd_label)
                if current_vol is None:
                    # No card detected - treat as removal
                    logger.info(f"Removal detected: no card found")
                    break
                if str(current_vol) != str(vol):
                    logger.info(f"Removal detected: different volume found ({current_vol} vs {vol})")
                    break
                
                # Card is still present and accessible - wait and check again
                time.sleep(cfg.poll_seconds)
            
            # Reset last processed volume so we can detect a new card
            last_processed_volume = None
            logger.info(f"Waiting for next '{cfg.sd_label}' card...")
            status.write(
                Status(
                    state="idle",
                    step="watch",
                    message="Waiting for SD card…",
                    hostname=get_hostname(),
                    ip=get_ip_address(),
                )
            )
    finally:
        # Clean up Watchdog watcher
        if use_watchdog:
            watcher.stop()
        # Clean up web server
        if web_server is not None:
            web_server.stop()

def cmd_doctor(args: argparse.Namespace) -> int:
    rc, results = run_doctor(
        base_dir=args.base_dir,
        sd_label=args.sd_label,
        mount_roots=args.mount_roots,
        db_path=args.db_path,
        s3_bucket=args.s3_bucket,
        min_free_gb=args.min_free_gb,
        skip_aws=args.skip_aws,
    )
    print(format_results(results))
    return rc


def _get_aws_cli_install_instructions() -> str:
    """Get platform-specific AWS CLI installation instructions."""
    system = platform.system().lower()
    if system == "darwin":
        return """Install AWS CLI v2 on macOS:

Option 1: Using Homebrew (recommended):
  brew install awscli

Option 2: Using the official installer:
  1. Download: https://awscli.amazonaws.com/AWSCLIV2.pkg
  2. Run the installer
  3. Verify: aws --version"""
    elif system == "linux":
        return """Install AWS CLI v2 on Linux:

Option 1: Using package manager (if available):
  # Debian/Ubuntu
  sudo apt-get update
  sudo apt-get install awscli

Option 2: Using the official installer:
  1. Download: curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  2. unzip awscliv2.zip
  3. sudo ./aws/install
  4. Verify: aws --version"""
    else:
        return """Install AWS CLI v2:
  1. Visit: https://aws.amazon.com/cli/
  2. Download the installer for your platform
  3. Follow the installation instructions
  4. Verify: aws --version"""


def cmd_setup(args: argparse.Namespace) -> int:
    """Interactive setup command that guides users through initial configuration."""
    print("GhostRoll Setup")
    print("=" * 60)
    print()
    
    # Run doctor checks
    print("Running system checks...")
    print()
    rc, results = run_doctor(
        base_dir=args.base_dir,
        sd_label=args.sd_label,
        mount_roots=args.mount_roots,
        db_path=args.db_path,
        s3_bucket=args.s3_bucket,
        min_free_gb=args.min_free_gb,
        skip_aws=False,
    )
    
    print(format_results(results))
    print()
    
    # Analyze results and provide guidance
    fatal_issues = [r for r in results if not r.ok and r.is_fatal]
    warnings = [r for r in results if not r.ok and not r.is_fatal]
    
    if not fatal_issues and not warnings:
        print("✅ All checks passed! Your GhostRoll setup looks good.")
        print()
        print("Next steps:")
        print("  1. Name your SD card volume label to 'auto-import'")
        print("  2. Run: ghostroll watch")
        return 0
    
    if fatal_issues:
        print("❌ Setup incomplete - please fix the following issues:")
        print()
        for issue in fatal_issues:
            print(f"  • {issue.name}: {issue.message}")
            
            # Provide specific guidance for common issues
            if issue.name == "aws_cli":
                print()
                print(_get_aws_cli_install_instructions())
                print()
            elif issue.name == "aws_identity":
                print()
                print("Configure AWS credentials:")
                print("  aws configure")
                print("  aws sts get-caller-identity  # Verify it works")
                print()
                print("Or manually edit files:")
                print("  ~/.aws/credentials  (copy from docs/aws/credentials.example)")
                print("  ~/.aws/config       (copy from docs/aws/config.example)")
                print()
        print()
    
    if warnings:
        print("⚠️  Warnings (non-fatal):")
        for warning in warnings:
            print(f"  • {warning.name}: {warning.message}")
        print()
    
    if fatal_issues:
        print("After fixing the issues above, run 'ghostroll setup' again to verify.")
        return 2
    else:
        print("You can proceed with GhostRoll, but consider addressing the warnings above.")
        return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghostroll", description="GhostRoll ingest pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="Interactive setup guide and system checks")
    _add_common_args(p_setup)
    p_setup.add_argument("--min-free-gb", type=float, default=2.0, help="Minimum free disk space required")
    p_setup.set_defaults(func=cmd_setup)

    p_doc = sub.add_parser("doctor", help="Run environment checks (AWS, mounts, disk, config)")
    _add_common_args(p_doc)
    p_doc.add_argument("--min-free-gb", type=float, default=2.0, help="Minimum free disk space required")
    p_doc.add_argument("--skip-aws", action="store_true", help="Skip AWS checks")
    p_doc.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="Run once against a specific volume path (debugging / one-shot)")
    _add_common_args(p_run)
    p_run.add_argument(
        "--volume",
        required=True,
        help="Mounted volume path (e.g. /Volumes/auto-import) OR a volume label (e.g. auto-import)",
    )
    p_run.add_argument("--always-create-session", action="store_true", help="Create a session even if no new files")
    p_run.add_argument("--session-id", default=None, help="Override session id (default: shoot-YYYY-MM-DD_HHMMSS)")
    p_run.set_defaults(func=cmd_run)

    p_watch = sub.add_parser("watch", help="Watch for SD insertion and run once per insert")
    _add_common_args(p_watch)
    p_watch.add_argument("--poll-seconds", type=float, default=None, help="Polling interval (default: 2)")
    p_watch.add_argument("--always-create-session", action="store_true", help="Create a session even if no new files")
    p_watch.add_argument("--web-enabled", action="store_true", default=None, help="Enable web interface (or set GHOSTROLL_WEB_ENABLED=true)")
    p_watch.add_argument("--no-web-enabled", dest="web_enabled", action="store_false", help="Disable web interface")
    p_watch.add_argument("--web-host", default=None, help="Web interface host (default: 127.0.0.1, or GHOSTROLL_WEB_HOST)")
    p_watch.add_argument("--web-port", type=int, default=None, help="Web interface port (default: 8080, or GHOSTROLL_WEB_PORT)")
    p_watch.set_defaults(func=cmd_watch)

    return p


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)


