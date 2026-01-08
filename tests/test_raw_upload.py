from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from ghostroll.cli import main as ghostroll_main
from ghostroll.pipeline import _build_raw_zip


def _make_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (2400, 1600), (120, 160, 200))
    img.save(path, format="JPEG", quality=92)


def _make_fake_raw(path: Path) -> None:
    """Create a fake RAW file (just binary data with RAW extension)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create a fake RAW file with some binary data
    # Real RAW files are typically 20-50MB, but for testing we'll use smaller
    fake_raw_data = b"FAKE_RAW_FILE_DATA" * 1000  # ~17KB
    path.write_bytes(fake_raw_data)


def test_build_raw_zip(tmp_path: Path):
    """Test RAW file compression function."""
    originals_dir = tmp_path / "originals"
    dcim_dir = originals_dir / "DCIM" / "100CANON"
    
    # Create some RAW files
    _make_fake_raw(dcim_dir / "IMG_0001.ARW")
    _make_fake_raw(dcim_dir / "IMG_0002.CR2")
    _make_fake_raw(dcim_dir / "IMG_0003.NEF")
    
    # Create some JPEGs (should be excluded)
    _make_jpeg(dcim_dir / "IMG_0001.JPG")
    _make_jpeg(dcim_dir / "IMG_0002.JPG")
    
    out_zip = tmp_path / "raw.zip"
    raw_count = _build_raw_zip(originals_dir=originals_dir, out_zip=out_zip, logger=None)
    
    assert raw_count == 3, f"Expected 3 RAW files, got {raw_count}"
    assert out_zip.exists(), "ZIP file should be created"
    assert out_zip.stat().st_size > 0, "ZIP file should not be empty"
    
    # Verify ZIP contents
    with zipfile.ZipFile(out_zip) as zf:
        names = set(zf.namelist())
        assert "DCIM/100CANON/IMG_0001.ARW" in names
        assert "DCIM/100CANON/IMG_0002.CR2" in names
        assert "DCIM/100CANON/IMG_0003.NEF" in names
        # JPEGs should NOT be in the ZIP
        assert "DCIM/100CANON/IMG_0001.JPG" not in names
        assert "DCIM/100CANON/IMG_0002.JPG" not in names


def test_build_raw_zip_no_raw_files(tmp_path: Path):
    """Test RAW zip creation when no RAW files exist."""
    originals_dir = tmp_path / "originals"
    dcim_dir = originals_dir / "DCIM" / "100CANON"
    
    # Create only JPEGs
    _make_jpeg(dcim_dir / "IMG_0001.JPG")
    _make_jpeg(dcim_dir / "IMG_0002.JPG")
    
    out_zip = tmp_path / "raw.zip"
    raw_count = _build_raw_zip(originals_dir=originals_dir, out_zip=out_zip, logger=None)
    
    assert raw_count == 0, "Should find 0 RAW files"
    # ZIP file is not created when there are no RAW files (optimization)
    assert not out_zip.exists(), "ZIP file should not be created when no RAW files exist"


def test_build_raw_zip_no_dcim(tmp_path: Path):
    """Test RAW zip creation when DCIM directory doesn't exist."""
    originals_dir = tmp_path / "originals"
    # Don't create DCIM directory
    
    out_zip = tmp_path / "raw.zip"
    raw_count = _build_raw_zip(originals_dir=originals_dir, out_zip=out_zip, logger=None)
    
    assert raw_count == 0, "Should return 0 when DCIM doesn't exist"
    # ZIP file may or may not be created, but should be safe


@pytest.mark.parametrize("upload_raw_files", [True, False])
def test_end_to_end_with_raw_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upload_raw_files: bool):
    """Test end-to-end pipeline with RAW files."""
    # Fake SD card mount
    vol = tmp_path / "vol"
    dcim = vol / "DCIM" / "100CANON"
    
    # Create both JPEG and RAW files
    _make_jpeg(dcim / "IMG_0001.JPG")
    _make_fake_raw(dcim / "IMG_0001.ARW")  # RAW version of same image
    _make_jpeg(dcim / "IMG_0002.JPG")
    _make_fake_raw(dcim / "IMG_0002.CR2")
    _make_fake_raw(dcim / "IMG_0003.NEF")  # RAW only, no JPEG
    
    # Mock boto3 availability and client
    monkeypatch.setattr('ghostroll.aws_boto3.BOTO3_AVAILABLE', True)
    
    mock_s3_client = MagicMock()
    mock_s3_client.upload_file = MagicMock()
    
    def fake_presign(operation, Params, ExpiresIn):
        bucket = Params.get('Bucket', '')
        key = Params.get('Key', '')
        return f"https://example.invalid/presigned?obj={bucket}/{key}&X-Amz-Signature=fake"
    
    mock_s3_client.generate_presigned_url = fake_presign
    
    # Mock head_object to return 404 for non-existent objects (for s3_object_exists)
    def fake_head_object(Bucket, Key):
        # For enhanced images check, return 404 (doesn't exist)
        if "enhanced" in Key:
            from botocore.exceptions import ClientError
            error_response = {'Error': {'Code': '404', 'Message': 'Not Found'}}
            raise ClientError(error_response, 'HeadObject')
        # For other objects, assume they exist
        return {}
    
    mock_s3_client.head_object = fake_head_object
    
    mock_config_class = MagicMock()
    mock_transfer_config_class = MagicMock()
    
    mock_boto3_module = MagicMock()
    mock_boto3_module.client.return_value = mock_s3_client
    mock_boto3_module.Config = mock_config_class
    mock_boto3_module.s3 = MagicMock()
    mock_boto3_module.s3.transfer = MagicMock()
    mock_boto3_module.s3.transfer.TransferConfig = mock_transfer_config_class
    
    monkeypatch.setattr('ghostroll.aws_boto3.boto3', mock_boto3_module)
    monkeypatch.setattr('ghostroll.aws_boto3.Config', mock_config_class)
    monkeypatch.setattr('ghostroll.aws_boto3.TransferConfig', mock_transfer_config_class)
    
    out = tmp_path / "out"
    monkeypatch.setenv("GHOSTROLL_BASE_DIR", str(out))
    monkeypatch.setenv("GHOSTROLL_DB_PATH", str(out / "ghostroll.db"))
    monkeypatch.setenv("GHOSTROLL_STATUS_PATH", str(out / "status.json"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_PATH", str(out / "status.png"))
    monkeypatch.setenv("GHOSTROLL_STATUS_IMAGE_SIZE", "320x240")
    monkeypatch.setenv("GHOSTROLL_S3_BUCKET", "photo-ingest-project")
    monkeypatch.setenv("GHOSTROLL_S3_PREFIX_ROOT", "sessions/")
    monkeypatch.setenv("GHOSTROLL_UPLOAD_RAW_FILES", "1" if upload_raw_files else "0")
    
    # Run pipeline
    with pytest.raises(SystemExit) as e:
        ghostroll_main(["run", "--volume", str(vol), "--always-create-session"])
    assert e.value.code == 0
    
    sessions = sorted(out.glob("shoot-*"))
    assert sessions, "expected a session directory"
    sess = sessions[-1]
    
    # Verify basic outputs
    assert (sess / "index.html").is_file()
    assert (sess / "share.txt").is_file()
    
    # Verify originals were copied
    assert (sess / "originals" / "DCIM" / "100CANON" / "IMG_0001.JPG").is_file()
    assert (sess / "originals" / "DCIM" / "100CANON" / "IMG_0001.ARW").is_file()
    assert (sess / "originals" / "DCIM" / "100CANON" / "IMG_0002.JPG").is_file()
    assert (sess / "originals" / "DCIM" / "100CANON" / "IMG_0002.CR2").is_file()
    assert (sess / "originals" / "DCIM" / "100CANON" / "IMG_0003.NEF").is_file()
    
    # Verify JPEG derivatives were created (from JPEG sources)
    assert (sess / "derived" / "share" / "100CANON" / "IMG_0001.jpg").is_file()
    assert (sess / "derived" / "share" / "100CANON" / "IMG_0002.jpg").is_file()
    
    # Check RAW zip upload behavior
    if upload_raw_files:
        # RAW zip should be created
        raw_zip = sess / "originals-raw.zip"
        assert raw_zip.exists(), "RAW zip should be created when upload_raw_files=True"
        assert raw_zip.stat().st_size > 0, "RAW zip should not be empty"
        
        # Verify ZIP contains RAW files
        with zipfile.ZipFile(raw_zip) as zf:
            names = set(zf.namelist())
            assert "DCIM/100CANON/IMG_0001.ARW" in names
            assert "DCIM/100CANON/IMG_0002.CR2" in names
            assert "DCIM/100CANON/IMG_0003.NEF" in names
            # JPEGs should NOT be in RAW zip
            assert "DCIM/100CANON/IMG_0001.JPG" not in names
        
            # Verify upload was called for RAW zip
            # upload_file is called with (local_path, bucket, key) or (local_path, bucket, key, Config=...)
            upload_calls = mock_s3_client.upload_file.call_args_list
            raw_zip_uploaded = False
            for call in upload_calls:
                # Check args: first arg is local path (Path object), second is bucket, third is key
                if len(call.args) >= 3:
                    key = call.args[2]  # Third positional arg is the S3 key
                    if "originals/raw.zip" in key:
                        raw_zip_uploaded = True
                        break
                # Also check kwargs
                if "Key" in call.kwargs and "originals/raw.zip" in call.kwargs["Key"]:
                    raw_zip_uploaded = True
                    break
            assert raw_zip_uploaded, f"RAW zip should be uploaded to S3. Upload calls: {[str(call) for call in upload_calls]}"
    else:
        # RAW zip should NOT be created when disabled
        raw_zip = sess / "originals-raw.zip"
        assert not raw_zip.exists(), "RAW zip should NOT be created when upload_raw_files=False"

