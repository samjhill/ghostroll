from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import load_config
from .logging_utils import setup_logging
from .pipeline import PipelineError, run_pipeline
from .volume_watch import find_candidate_volumes, pick_volume_with_dcim


def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sd-label", default=None, help="SD card volume label to watch (default: auto-import)")
    p.add_argument("--base-dir", default=None, help="Base output directory (default: ~/ghostroll)")
    p.add_argument("--db-path", default=None, help="SQLite DB path for dedupe (default: ~/.ghostroll/ghostroll.db)")
    p.add_argument("--s3-bucket", default=None, help="S3 bucket name (default: photo-ingest-project)")
    p.add_argument("--s3-prefix-root", default=None, help="S3 prefix root (default: sessions/)")
    p.add_argument("--presign-expiry-seconds", type=int, default=None, help="Presign expiry seconds (default: 604800)")
    p.add_argument("--verbose", action="store_true", help="Verbose logs")


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(
        sd_label=args.sd_label,
        base_output_dir=args.base_dir,
        db_path=args.db_path,
        s3_bucket=args.s3_bucket,
        s3_prefix_root=args.s3_prefix_root,
        presign_expiry_seconds=args.presign_expiry_seconds,
    )

    # Accept either an explicit mounted path (recommended) or a volume label like "auto-import".
    vol_arg = str(args.volume)
    if "/" not in vol_arg and "\\" not in vol_arg:
        # Interpret as label under /Volumes (macOS), including "auto-import 1" suffixes.
        guessed = pick_volume_with_dcim(Path("/Volumes"), label=vol_arg)
        volume = guessed if guessed is not None else Path(vol_arg).resolve()
    else:
        volume = Path(vol_arg).resolve()
    logger = setup_logging(session_dir=None, verbose=args.verbose)
    logger.info(f"Volume: {volume}")
    try:
        sp, url = run_pipeline(
            cfg=cfg,
            volume_path=volume,
            logger=logger,
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
        if isinstance(e, PipelineError) and "no DCIM directory" in str(e) and ("/Volumes" not in str(volume)):
            logger.error("Tip: on macOS, your SD card is usually mounted under /Volumes/<label>. Example: --volume /Volumes/auto-import")
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
    )
    logger = setup_logging(session_dir=None, verbose=args.verbose)

    logger.info(f"GhostRoll watching for SD volume '{cfg.sd_label}' under {cfg.volumes_root} ...")
    logger.info("Insert the SD card to begin.")

    while True:
        vol = pick_volume_with_dcim(cfg.volumes_root, label=cfg.sd_label)
        if vol is None:
            cands = find_candidate_volumes(cfg.volumes_root, label=cfg.sd_label)
            if cands:
                logger.warning(f"Volume detected ({', '.join([c.name for c in cands])}) but no DCIM directory. Waiting...")
            time.sleep(cfg.poll_seconds)
            continue

        logger.info(f"Detected camera volume: {vol}")
        rc = cmd_run(
            argparse.Namespace(
                sd_label=cfg.sd_label,
                base_dir=str(cfg.base_output_dir),
                db_path=str(cfg.db_path),
                s3_bucket=cfg.s3_bucket,
                s3_prefix_root=cfg.s3_prefix_root,
                presign_expiry_seconds=cfg.presign_expiry_seconds,
                verbose=args.verbose,
                volume=str(vol),
                always_create_session=args.always_create_session,
                session_id=None,
            )
        )
        if rc != 0:
            logger.error(f"Run failed with exit code {rc}. Waiting for card removal before retrying.")

        logger.info("Remove SD card to run again.")
        while pick_volume_with_dcim(cfg.volumes_root, label=cfg.sd_label) is not None:
            time.sleep(cfg.poll_seconds)
        logger.info(f"Waiting for next '{cfg.sd_label}' card...")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghostroll", description="GhostRoll ingest pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

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


