from __future__ import annotations

import os
import stat
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ghostroll.cli import _is_mounted, build_parser, cmd_doctor, cmd_run, cmd_watch, main
from ghostroll.config import Config
from ghostroll.doctor import CheckResult, run_doctor
from ghostroll.pipeline import PipelineError, run_pipeline
from ghostroll.status import Status, StatusWriter


def test_build_parser():
    parser = build_parser()
    assert parser.prog == "ghostroll"
    
    # Test subcommands exist
    subparsers = {action.dest: action for action in parser._actions if hasattr(action, 'choices')}
    assert 'cmd' in subparsers
    
    # Test that required subcommand works
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_is_mounted(tmp_path: Path):
    # Create a fake /proc/mounts
    proc_mounts = tmp_path / "proc_mounts"
    proc_mounts.write_text("/dev/sda1 /mnt/test ext4 rw 0 0\n")
    
    with patch("ghostroll.cli.Path") as mock_path:
        mock_path.return_value = proc_mounts
        mock_path.read_text = proc_mounts.read_text
        
        # Test with matching mount
        result = _is_mounted(Path("/mnt/test"))
        assert result is True
        
        # Test with non-matching mount
        result = _is_mounted(Path("/mnt/other"))
        assert result is False


def test_is_mounted_no_proc_mounts(tmp_path: Path):
    # Test when /proc/mounts doesn't exist
    with patch("ghostroll.cli.Path") as mock_path_class:
        mock_path = MagicMock()
        mock_path.read_text.side_effect = FileNotFoundError()
        mock_path_class.return_value = mock_path
        
        result = _is_mounted(Path("/mnt/test"))
        assert result is False


def test_cmd_run_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup fake volume
    vol = tmp_path / "vol"
    dcim = vol / "DCIM" / "100CANON"
    dcim.mkdir(parents=True)
    (dcim / "IMG_0001.JPG").write_text("fake")
    
    # Setup fake aws
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    
    # Setup config
    out = tmp_path / "out"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(out))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(out / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.volume = str(vol)
    args.sd_label = None
    args.base_dir = None
    args.db_path = None
    args.s3_bucket = None
    args.s3_prefix_root = None
    args.presign_expiry_seconds = None
    args.mount_roots = "/Volumes,/media,/run/media,/mnt"
    args.status_path = None
    args.status_image_path = None
    args.status_image_size = None
    args.verbose = False
    args.always_create_session = True
    args.session_id = None
    
    with patch("ghostroll.cli.run_pipeline") as mock_run:
        mock_run.return_value = (MagicMock(), "https://example.com/share")
        result = cmd_run(args)
        assert result == 0
        mock_run.assert_called_once()


def test_cmd_run_no_new_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup fake volume
    vol = tmp_path / "vol"
    dcim = vol / "DCIM" / "100CANON"
    dcim.mkdir(parents=True)
    
    # Setup fake aws
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    
    # Setup config
    out = tmp_path / "out"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(out))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(out / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.volume = str(vol)
    args.sd_label = None
    args.base_dir = None
    args.db_path = None
    args.s3_bucket = None
    args.s3_prefix_root = None
    args.presign_expiry_seconds = None
    args.mount_roots = "/Volumes,/media,/run/media,/mnt"
    args.status_path = None
    args.status_image_path = None
    args.status_image_size = None
    args.verbose = False
    args.always_create_session = False
    args.session_id = None
    
    with patch("ghostroll.cli.run_pipeline") as mock_run:
        mock_run.return_value = (None, None)
        result = cmd_run(args)
        assert result == 0


def test_cmd_run_pipeline_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup config
    out = tmp_path / "out"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(out))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(out / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.volume = str(tmp_path / "vol")
    args.sd_label = None
    args.base_dir = None
    args.db_path = None
    args.s3_bucket = None
    args.s3_prefix_root = None
    args.presign_expiry_seconds = None
    args.mount_roots = "/Volumes,/media,/run/media,/mnt"
    args.status_path = None
    args.status_image_path = None
    args.status_image_size = None
    args.verbose = False
    args.always_create_session = False
    args.session_id = None
    
    with patch("ghostroll.cli.run_pipeline") as mock_run:
        mock_run.side_effect = PipelineError("no DCIM directory")
        result = cmd_run(args)
        assert result == 2


def test_cmd_run_generic_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Setup config
    out = tmp_path / "out"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(out))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(out / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.volume = str(tmp_path / "vol")
    args.sd_label = None
    args.base_dir = None
    args.db_path = None
    args.s3_bucket = None
    args.s3_prefix_root = None
    args.presign_expiry_seconds = None
    args.mount_roots = "/Volumes,/media,/run/media,/mnt"
    args.status_path = None
    args.status_image_path = None
    args.status_image_size = None
    args.verbose = False
    args.always_create_session = False
    args.session_id = None
    
    with patch("ghostroll.cli.run_pipeline") as mock_run:
        mock_run.side_effect = ValueError("Something went wrong")
        result = cmd_run(args)
        assert result == 2


def test_cmd_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(tmp_path / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.base_dir = None
    args.sd_label = None
    args.mount_roots = None
    args.db_path = None
    args.s3_bucket = None
    args.min_free_gb = 2.0
    args.skip_aws = True
    
    with patch("ghostroll.cli.run_doctor") as mock_doctor:
        mock_doctor.return_value = (0, [CheckResult("test", True, "OK")])
        with patch("ghostroll.cli.format_results") as mock_format:
            mock_format.return_value = "[OK] test: OK"
            result = cmd_doctor(args)
            assert result == 0
            mock_doctor.assert_called_once()
            mock_format.assert_called_once()


def test_cmd_watch_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(tmp_path / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "test-bucket")
    
    args = MagicMock()
    args.sd_label = None
    args.base_dir = None
    args.db_path = None
    args.s3_bucket = None
    args.s3_prefix_root = None
    args.presign_expiry_seconds = None
    args.poll_seconds = 0.1
    args.mount_roots = "/Volumes,/media,/run/media,/mnt"
    args.status_path = None
    args.status_image_path = None
    args.status_image_size = None
    args.verbose = False
    args.always_create_session = False
    
    with patch("ghostroll.cli.pick_mount_with_dcim") as mock_pick:
        # First call returns None (no card), second call raises KeyboardInterrupt to exit
        mock_pick.side_effect = [None, KeyboardInterrupt()]
        with patch("ghostroll.cli.time.sleep"):
            with pytest.raises(KeyboardInterrupt):
                cmd_watch(args)


def test_main():
    with patch("ghostroll.cli.build_parser") as mock_parser:
        mock_parser_instance = MagicMock()
        mock_parser.return_value = mock_parser_instance
        mock_args = MagicMock()
        mock_args.func = MagicMock(return_value=0)
        mock_parser_instance.parse_args.return_value = mock_args
        
        with pytest.raises(SystemExit) as exc_info:
            main(["doctor"])
        assert exc_info.value.code == 0
        mock_args.func.assert_called_once()

