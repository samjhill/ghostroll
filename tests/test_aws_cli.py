from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from ghostroll.aws_cli import AwsCliError, ensure_aws_cli, s3_cp, s3_presign


def _write_fake_aws(bin_dir: Path, *, fail: bool = False) -> None:
    aws = bin_dir / "aws"
    if fail:
        script = "#!/usr/bin/env bash\nexit 1\n"
    else:
        script = textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$1" == "s3" && "$2" == "cp" ]]; then
              exit 0
            fi
            if [[ "$1" == "s3" && "$2" == "presign" ]]; then
              uri="$3"
              key="${uri#s3://}"
              echo "https://example.invalid/presigned?obj=${key}&X-Amz-Signature=fake"
              exit 0
            fi
            echo "fake aws: unsupported args: $*" >&2
            exit 2
            """
        )
    aws.write_text(script, encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)


def test_ensure_aws_cli_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_aws(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    # Should not raise
    ensure_aws_cli()


def test_ensure_aws_cli_failure(monkeypatch: pytest.MonkeyPatch):
    # Mock shutil.which to return None
    monkeypatch.setattr("ghostroll.aws_cli.shutil.which", lambda x: None)

    with pytest.raises(AwsCliError, match="aws CLI not found"):
        ensure_aws_cli()


def test_s3_cp_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_aws(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    # Should not raise
    s3_cp(test_file, bucket="test-bucket", key="test/key.txt")


def test_s3_cp_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_aws(bin_dir, fail=True)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    with pytest.raises(AwsCliError, match="Command failed"):
        s3_cp(test_file, bucket="test-bucket", key="test/key.txt", retries=1)


def test_s3_presign_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_aws(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    url = s3_presign(bucket="test-bucket", key="test/key.txt", expires_in_seconds=3600)

    assert "https://example.invalid/presigned" in url
    assert "test/key.txt" in url
    assert "X-Amz-Signature=fake" in url


def test_s3_presign_empty_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\necho ''\nexit 0\n",
        encoding="utf-8",
    )
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    with pytest.raises(AwsCliError, match="empty output"):
        s3_presign(bucket="test-bucket", key="test/key.txt", expires_in_seconds=3600)

