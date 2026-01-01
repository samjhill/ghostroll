from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CmdResult:
    stdout: str
    stderr: str


class AwsCliError(RuntimeError):
    pass


def ensure_aws_cli() -> None:
    if shutil.which("aws") is None:
        raise AwsCliError(
            "aws CLI not found on PATH. Install/configure AWS CLI v2, then retry."
        )


def _run(cmd: list[str], *, retries: int = 3, backoff_seconds: float = 1.5) -> CmdResult:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, retries + 1):
        last = subprocess.run(cmd, text=True, capture_output=True)
        if last.returncode == 0:
            return CmdResult(stdout=last.stdout.strip(), stderr=last.stderr.strip())
        if attempt < retries:
            time.sleep(backoff_seconds * attempt)
    assert last is not None
    raise AwsCliError(
        f"Command failed ({last.returncode}): {' '.join(cmd)}\n"
        f"stdout:\n{last.stdout}\n\nstderr:\n{last.stderr}"
    )


def s3_cp(local_path: Path, *, bucket: str, key: str, retries: int = 3) -> None:
    ensure_aws_cli()
    s3_uri = f"s3://{bucket}/{key}"
    _run(
        ["aws", "s3", "cp", str(local_path), s3_uri, "--only-show-errors", "--no-progress"],
        retries=retries,
    )


def s3_presign(*, bucket: str, key: str, expires_in_seconds: int) -> str:
    ensure_aws_cli()
    s3_uri = f"s3://{bucket}/{key}"
    res = _run(
        ["aws", "s3", "presign", s3_uri, "--expires-in", str(expires_in_seconds)],
        retries=3,
    )
    if not res.stdout:
        raise AwsCliError("aws s3 presign returned empty output")
    return res.stdout


