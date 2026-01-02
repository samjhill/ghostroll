from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ghostroll.doctor import (
    CheckResult,
    _bytes_human,
    _check_aws_cli,
    _check_aws_identity,
    _check_disk_space,
    _check_mount_roots,
    _check_s3_access,
    _check_sd_detection,
    _check_status_paths,
    _run,
    format_results,
    run_doctor,
)
from ghostroll.config import Config, load_config


def test_bytes_human():
    assert _bytes_human(0) == "0B"
    assert _bytes_human(1023) == "1023B"
    assert _bytes_human(1024) == "1.0KB"
    assert _bytes_human(1024 * 1024) == "1.0MB"
    assert _bytes_human(1024 * 1024 * 1024) == "1.0GB"
    assert _bytes_human(1024 * 1024 * 1024 * 1024) == "1.0TB"


def test_run():
    result = _run(["echo", "hello"])
    assert result[0] == 0
    assert "hello" in result[1]
    
    result = _run(["false"])
    assert result[0] != 0


def test_check_disk_space_sufficient(tmp_path: Path):
    cfg = MagicMock()
    cfg.base_output_dir = tmp_path
    
    result = _check_disk_space(tmp_path, min_free_gb=0.001)
    assert result.ok is True
    assert "Free space" in result.message
    assert result.is_fatal is False


def test_check_disk_space_insufficient(tmp_path: Path):
    # Mock disk_usage to return very little free space
    with patch("ghostroll.doctor.shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(free=1024 * 1024)  # 1MB
        result = _check_disk_space(tmp_path, min_free_gb=2.0)
        assert result.ok is False
        assert result.is_fatal is True


def test_check_disk_space_error(tmp_path: Path):
    with patch("ghostroll.doctor.shutil.disk_usage") as mock_usage:
        mock_usage.side_effect = PermissionError("Access denied")
        result = _check_disk_space(tmp_path, min_free_gb=2.0)
        assert result.ok is False
        assert result.is_fatal is False
        assert "Failed to check" in result.message


def test_check_status_paths_success(tmp_path: Path):
    cfg = MagicMock()
    cfg.status_path = tmp_path / "status.json"
    cfg.status_image_path = tmp_path / "status.png"
    
    result = _check_status_paths(cfg)
    assert result.ok is True
    assert "Writable" in result.message
    assert cfg.status_path.exists()


def test_check_status_paths_error(tmp_path: Path):
    cfg = MagicMock()
    # Use a path that can't be created (root path on Unix)
    cfg.status_path = Path("/nonexistent/dir/status.json")
    cfg.status_image_path = Path("/nonexistent/dir/status.png")
    
    result = _check_status_paths(cfg)
    assert result.ok is False
    assert "not writable" in result.message
    assert result.is_fatal is False


def test_check_mount_roots_all_exist(tmp_path: Path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    root2.mkdir()
    
    cfg = MagicMock()
    cfg.mount_roots = [root1, root2]
    
    result = _check_mount_roots(cfg)
    assert result.ok is True
    assert "Mount roots" in result.message


def test_check_mount_roots_some_missing(tmp_path: Path):
    root1 = tmp_path / "root1"
    root2 = tmp_path / "root2"
    root1.mkdir()
    # root2 doesn't exist
    
    cfg = MagicMock()
    cfg.mount_roots = [root1, root2]
    
    result = _check_mount_roots(cfg)
    assert result.ok is True
    assert "missing" in result.message.lower()


def test_check_aws_cli_found():
    with patch("ghostroll.doctor.shutil.which", return_value="/usr/bin/aws"):
        result = _check_aws_cli()
        assert result.ok is True
        assert "found" in result.message.lower()


def test_check_aws_cli_not_found():
    with patch("ghostroll.doctor.shutil.which", return_value=None):
        result = _check_aws_cli()
        assert result.ok is False
        assert result.is_fatal is True
        assert "not found" in result.message.lower()


def test_check_aws_identity_success():
    with patch("ghostroll.doctor._run") as mock_run:
        mock_run.return_value = (0, '{"UserId":"test"}', "")
        result = _check_aws_identity()
        assert result.ok is True
        assert "identity OK" in result.message


def test_check_aws_identity_failure():
    with patch("ghostroll.doctor._run") as mock_run:
        mock_run.return_value = (1, "", "Access denied")
        result = _check_aws_identity()
        assert result.ok is False
        assert result.is_fatal is True
        assert "failed" in result.message.lower()


def test_check_s3_access_success():
    cfg = MagicMock()
    cfg.s3_bucket = "test-bucket"
    
    with patch("ghostroll.doctor._run") as mock_run:
        mock_run.return_value = (0, "", "")
        result = _check_s3_access(cfg)
        assert result.ok is True
        assert "S3 access OK" in result.message


def test_check_s3_access_failure():
    cfg = MagicMock()
    cfg.s3_bucket = "test-bucket"
    
    with patch("ghostroll.doctor._run") as mock_run:
        mock_run.return_value = (1, "", "Access denied")
        result = _check_s3_access(cfg)
        assert result.ok is False
        assert result.is_fatal is False  # S3 access failure is not fatal


def test_check_sd_detection_found(tmp_path: Path):
    vol = tmp_path / "vol"
    dcim = vol / "DCIM"
    dcim.mkdir(parents=True)
    
    cfg = MagicMock()
    cfg.mount_roots = [tmp_path]
    cfg.sd_label = "vol"
    
    with patch("ghostroll.doctor.pick_mount_with_dcim", return_value=vol):
        result = _check_sd_detection(cfg)
        assert result.ok is True
        assert "Detected" in result.message


def test_check_sd_detection_not_found():
    cfg = MagicMock()
    cfg.mount_roots = [Path("/nonexistent")]
    cfg.sd_label = "auto-import"
    
    with patch("ghostroll.doctor.pick_mount_with_dcim", return_value=None):
        with patch("ghostroll.doctor.find_candidate_mounts", return_value=[]):
            result = _check_sd_detection(cfg)
            assert result.ok is True
            assert "No card detected" in result.message


def test_run_doctor_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(tmp_path / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    with patch("ghostroll.doctor._check_aws_cli") as mock_aws:
        mock_aws.return_value = CheckResult("aws_cli", True, "OK")
        with patch("ghostroll.doctor._check_aws_identity") as mock_identity:
            mock_identity.return_value = CheckResult("aws_identity", True, "OK")
            with patch("ghostroll.doctor._check_s3_access") as mock_s3:
                mock_s3.return_value = CheckResult("s3_access", True, "OK")
                
                rc, results = run_doctor(skip_aws=False)
                assert isinstance(rc, int)
                assert len(results) > 0
                assert all(isinstance(r, CheckResult) for r in results)


def test_run_doctor_skip_aws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(tmp_path / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    rc, results = run_doctor(skip_aws=True)
    assert isinstance(rc, int)
    # Should not have AWS-related checks
    aws_checks = [r for r in results if "aws" in r.name.lower()]
    assert len(aws_checks) == 0


def test_run_doctor_fatal_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(tmp_path / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    with patch("ghostroll.doctor._check_aws_cli") as mock_aws:
        mock_aws.return_value = CheckResult("aws_cli", False, "Not found", is_fatal=True)
        
        rc, results = run_doctor(skip_aws=False)
        assert rc == 2  # Fatal error should return 2


def test_format_results():
    results = [
        CheckResult("test1", True, "OK"),
        CheckResult("test2", False, "Failed", is_fatal=True),
        CheckResult("test3", False, "Warning", is_fatal=False),
    ]
    
    output = format_results(results)
    assert "[OK]" in output
    assert "[FAIL]" in output
    assert "[WARN]" in output
    assert "test1" in output
    assert "test2" in output
    assert "test3" in output

