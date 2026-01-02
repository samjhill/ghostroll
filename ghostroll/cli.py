from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import load_config
from .doctor import format_results, run_doctor
from .logging_utils import setup_logging
from .pipeline import PipelineError, run_pipeline
from .status import Status, StatusWriter, get_hostname, get_ip_address
from .volume_watch import find_candidate_mounts, pick_mount_with_dcim


def _is_mounted(where: Path) -> bool:
    """
    Returns True if `where` is currently a mountpoint (checks /proc/mounts).
    Important: does NOT touch the filesystem under `where`, so it won't trigger systemd automount.
    """
    try:
        mounts_text = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    # /proc/mounts fields: <src> <target> <fstype> <opts> ...
    # Targets escape spaces as \040.
    target = str(where).replace(" ", "\\040")
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target:
            return True
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
    p.add_argument("--verbose", action="store_true", help="Verbose logs")


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
    logger = setup_logging(session_dir=None, verbose=args.verbose)
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
    except (PipelineError, Exception) as e:
        logger.error(str(e))
        if isinstance(e, PipelineError) and "no DCIM directory" in str(e):
            logger.error("Tip: pass the mounted volume path (example: /Volumes/auto-import on macOS, /media/pi/auto-import on Linux).")
        status.write(Status(state="error", step="error", message=str(e), volume=str(volume)))
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
    )
    logger = setup_logging(session_dir=None, verbose=args.verbose)
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

    while True:
        vol = pick_mount_with_dcim(cfg.mount_roots, label=cfg.sd_label)
        if vol is None:
            cands = find_candidate_mounts(cfg.mount_roots, label=cfg.sd_label)
            if cands:
                logger.warning(f"Volume detected ({', '.join([c.name for c in cands])}) but no DCIM directory. Waiting...")
            time.sleep(cfg.poll_seconds)
            continue

        logger.info(f"Detected camera volume: {vol}")
        logger.debug(f"Volume path: {vol}")
        logger.debug(f"DCIM directory: {vol / 'DCIM'}")
        status.write(Status(state="running", step="detected", message="SD card detected.", volume=str(vol)))
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
                verbose=args.verbose,
                volume=str(vol),
                always_create_session=args.always_create_session,
                session_id=None,
            )
        )
        if rc != 0:
            logger.error(f"Run failed with exit code {rc}. Waiting for card removal before retrying.")

        logger.info("Remove SD card to run again.")
        # On Raspberry Pi OS Lite, we often rely on systemd automount (e.g. /mnt/auto-import).
        # Continuously probing vol/DCIM can keep the automount "busy". For removal detection, avoid touching
        # the mountpoint and instead check:
        # - /dev/disk/by-label/<label> (udev symlink; disappears when the partition is gone)
        # - mount table (/proc/mounts) for the last-detected mountpoint path
        by_label_root = Path("/dev/disk/by-label")
        by_label = by_label_root / cfg.sd_label
        last_mountpoint = Path(vol)
        while True:
            label_present = by_label.exists() if by_label_root.is_dir() else False
            mounted = _is_mounted(last_mountpoint)
            if (by_label_root.is_dir() and not label_present) or not mounted:
                break
            time.sleep(cfg.poll_seconds)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghostroll", description="GhostRoll ingest pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

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
    p_watch.set_defaults(func=cmd_watch)

    return p


def main(argv: list[str] | None = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    rc = args.func(args)
    raise SystemExit(rc)


