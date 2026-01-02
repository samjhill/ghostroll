from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load_config
from .volume_watch import find_candidate_mounts, pick_mount_with_dcim


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    message: str
    is_fatal: bool = False


def _run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, text=True, capture_output=True)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def _bytes_human(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            return f"{f:.1f}{u}" if u != "B" else f"{int(f)}B"
        f /= 1024.0
    return f"{int(n)}B"


def _check_disk_space(path: Path, *, min_free_gb: float) -> CheckResult:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        ok = free_gb >= min_free_gb
        return CheckResult(
            name="disk_space",
            ok=ok,
            message=f"Free space at {path}: {_bytes_human(usage.free)} (min {min_free_gb:.1f}GB)",
            is_fatal=not ok,
        )
    except Exception as e:
        return CheckResult("disk_space", False, f"Failed to check disk space: {e}", is_fatal=False)


def _check_status_paths(cfg: Config) -> CheckResult:
    try:
        cfg.status_path.parent.mkdir(parents=True, exist_ok=True)
        cfg.status_image_path.parent.mkdir(parents=True, exist_ok=True)
        # Touch writeability (atomic tmp)
        tmp = cfg.status_path.with_suffix(cfg.status_path.suffix + ".tmp")
        tmp.write_text("{}", encoding="utf-8")
        tmp.replace(cfg.status_path)
        return CheckResult(
            "status_paths",
            True,
            f"Writable: {cfg.status_path} and {cfg.status_image_path}",
        )
    except Exception as e:
        return CheckResult(
            "status_paths",
            False,
            f"Status output not writable: {e}",
            is_fatal=False,
        )


def _check_mount_roots(cfg: Config) -> CheckResult:
    missing = [str(p) for p in cfg.mount_roots if not p.exists()]
    if missing:
        return CheckResult(
            "mount_roots",
            True,
            f"Mount roots configured (some missing is OK): missing={', '.join(missing)}",
        )
    return CheckResult("mount_roots", True, f"Mount roots: {', '.join([str(p) for p in cfg.mount_roots])}")


def _check_sd_detection(cfg: Config) -> CheckResult:
    cands = find_candidate_mounts(cfg.mount_roots, label=cfg.sd_label)
    vol = pick_mount_with_dcim(cfg.mount_roots, label=cfg.sd_label)
    if vol is not None:
        return CheckResult("sd_detection", True, f"Detected camera card: {vol}")
    if cands:
        return CheckResult(
            "sd_detection",
            True,
            f"Volume(s) detected but no DCIM yet: {', '.join([str(c) for c in cands])}",
        )
    return CheckResult("sd_detection", True, f"No card detected for label '{cfg.sd_label}' (insert card to test)")


def _check_aws_cli() -> CheckResult:
    if shutil.which("aws") is None:
        return CheckResult(
            "aws_cli",
            False,
            "aws CLI not found on PATH. Install AWS CLI v2 and configure credentials.",
            is_fatal=True,
        )
    return CheckResult("aws_cli", True, "aws CLI found")


def _check_aws_identity() -> CheckResult:
    rc, out, err = _run(["aws", "sts", "get-caller-identity"])
    if rc != 0:
        return CheckResult(
            "aws_identity",
            False,
            f"aws sts get-caller-identity failed (rc={rc}). stderr={err}",
            is_fatal=True,
        )
    return CheckResult("aws_identity", True, f"AWS identity OK: {out}")


def _check_s3_access(cfg: Config) -> CheckResult:
    # Minimal check: can list the bucket (may require s3:ListBucket). If it fails, we warn.
    rc, _out, err = _run(["aws", "s3", "ls", f"s3://{cfg.s3_bucket}"])
    if rc != 0:
        return CheckResult(
            "s3_access",
            False,
            f"Could not list s3://{cfg.s3_bucket} (this may be OK if ListBucket isn't allowed). stderr={err}",
            is_fatal=False,
        )
    return CheckResult("s3_access", True, f"S3 access OK for bucket: {cfg.s3_bucket}")


def run_doctor(
    *,
    base_dir: str | None = None,
    sd_label: str | None = None,
    mount_roots: str | None = None,
    db_path: str | None = None,
    s3_bucket: str | None = None,
    min_free_gb: float = 2.0,
    skip_aws: bool = False,
) -> tuple[int, list[CheckResult]]:
    cfg = load_config(
        base_output_dir=base_dir,
        sd_label=sd_label,
        mount_roots=mount_roots,
        db_path=db_path,
        s3_bucket=s3_bucket,
    )

    results: list[CheckResult] = []
    results.append(CheckResult("config", True, f"Base dir: {cfg.base_output_dir} | Bucket: {cfg.s3_bucket}"))
    results.append(_check_mount_roots(cfg))
    results.append(_check_sd_detection(cfg))
    results.append(_check_disk_space(cfg.base_output_dir, min_free_gb=min_free_gb))
    results.append(_check_status_paths(cfg))

    if not skip_aws:
        results.append(_check_aws_cli())
        # Only attempt identity/s3 checks if aws exists
        if results[-1].ok:
            results.append(_check_aws_identity())
            if results[-1].ok:
                results.append(_check_s3_access(cfg))

    fatal = any((not r.ok) and r.is_fatal for r in results)
    rc = 2 if fatal else 0
    return rc, results


def format_results(results: list[CheckResult]) -> str:
    lines: list[str] = []
    for r in results:
        status = "OK" if r.ok else ("FAIL" if r.is_fatal else "WARN")
        lines.append(f"[{status}] {r.name}: {r.message}")
    return os.linesep.join(lines)


