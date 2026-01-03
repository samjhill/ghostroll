from __future__ import annotations

import platform
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


def _get_aws_cli_install_hint() -> str:
    """Get platform-specific AWS CLI installation hint."""
    system = platform.system().lower()
    if system == "darwin":
        return "Install with: brew install awscli (or see https://aws.amazon.com/cli/)"
    elif system == "linux":
        return "Install with: sudo apt-get install awscli (or see https://aws.amazon.com/cli/)"
    else:
        return "See https://aws.amazon.com/cli/ for installation instructions"


def ensure_aws_cli() -> None:
    if shutil.which("aws") is None:
        hint = _get_aws_cli_install_hint()
        raise AwsCliError(
            f"aws CLI not found on PATH.\n"
            f"{hint}\n"
            f"After installation, verify with: aws --version"
        )


def _parse_aws_error(stderr: str) -> str | None:
    """Parse common AWS CLI errors and return actionable guidance."""
    stderr_lower = stderr.lower()
    
    if "unable to locate credentials" in stderr_lower or "no credentials" in stderr_lower:
        return (
            "AWS credentials not configured.\n"
            "  Run: aws configure\n"
            "  Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        )
    if "access denied" in stderr_lower or "forbidden" in stderr_lower:
        return (
            "Access denied. Check your AWS IAM permissions:\n"
            "  - s3:PutObject for uploading files\n"
            "  - s3:GetObject for presigning URLs\n"
            "  Verify with: aws sts get-caller-identity"
        )
    if "no such bucket" in stderr_lower or "does not exist" in stderr_lower:
        return (
            "S3 bucket does not exist or is not accessible.\n"
            "  Verify the bucket name and your access permissions.\n"
            "  Check with: aws s3 ls s3://<bucket-name>"
        )
    if "network" in stderr_lower or "timeout" in stderr_lower or "connection" in stderr_lower:
        return (
            "Network error connecting to AWS.\n"
            "  Check your internet connection and AWS service status.\n"
            "  If using a proxy, configure it with: aws configure set proxy.*"
        )
    if "invalid" in stderr_lower and "key" in stderr_lower:
        return (
            "Invalid S3 key (path). Check for special characters or path issues."
        )
    
    return None


def _run(cmd: list[str], *, retries: int = 3, backoff_seconds: float = 1.5) -> CmdResult:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, retries + 1):
        last = subprocess.run(cmd, text=True, capture_output=True)
        if last.returncode == 0:
            return CmdResult(stdout=last.stdout.strip(), stderr=last.stderr.strip())
        if attempt < retries:
            time.sleep(backoff_seconds * attempt)
    assert last is not None
    
    # Try to provide actionable guidance
    guidance = _parse_aws_error(last.stderr)
    error_msg = f"Command failed ({last.returncode}): {' '.join(cmd)}"
    
    if guidance:
        error_msg += f"\n\n{guidance}\n"
    
    error_msg += f"\nFull error output:\nstdout:\n{last.stdout}\n\nstderr:\n{last.stderr}"
    
    raise AwsCliError(error_msg)


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
        raise AwsCliError(
            f"aws s3 presign returned empty output for {s3_uri}.\n"
            f"This may indicate the object doesn't exist or you lack s3:GetObject permission.\n"
            f"stderr: {res.stderr}"
        )
    return res.stdout


