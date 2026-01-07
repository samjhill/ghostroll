from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from ghostroll.cli import main as ghostroll_main


def _make_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (2400, 1600), (120, 160, 200))
    img.save(path, format="JPEG", quality=92)


@pytest.mark.parametrize("workers", [(2, 2, 4)])
def test_end_to_end_offline_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers) -> None:
    process_workers, upload_workers, presign_workers = workers

    # Fake SD card mount
    vol = tmp_path / "vol"
    dcim = vol / "DCIM" / "100CANON"
    _make_jpeg(dcim / "IMG_0001.JPG")

    # Mock boto3 availability and client
    monkeypatch.setattr('ghostroll.aws_boto3.BOTO3_AVAILABLE', True)
    
    mock_s3_client = MagicMock()
    
    # Mock upload_file to succeed (no-op)
    mock_s3_client.upload_file = MagicMock()
    
    # Mock generate_presigned_url to return fake URLs
    def fake_presign(operation, Params, ExpiresIn):
        bucket = Params.get('Bucket', '')
        key = Params.get('Key', '')
        return f"https://example.invalid/presigned?obj={bucket}/{key}&X-Amz-Signature=fake"
    
    mock_s3_client.generate_presigned_url = fake_presign
    
    # Mock boto3 module with proper Config and TransferConfig
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
    monkeypatch.setenv("GHOSTROLL_PROCESS_WORKERS", str(process_workers))
    monkeypatch.setenv("GHOSTROLL_UPLOAD_WORKERS", str(upload_workers))
    monkeypatch.setenv("GHOSTROLL_PRESIGN_WORKERS", str(presign_workers))

    # Run once
    with pytest.raises(SystemExit) as e:
        ghostroll_main(["run", "--volume", str(vol), "--always-create-session"])
    assert e.value.code == 0

    sessions = sorted(out.glob("shoot-*"))
    assert sessions, "expected a session directory"
    sess = sessions[-1]

    assert (sess / "index.html").is_file()
    assert (sess / "index.s3.html").is_file()
    assert (sess / "share.txt").is_file()
    assert (sess / "share.zip").is_file()
    assert (sess / "share-qr.png").is_file(), "QR code PNG should be created"
    assert (sess / "derived" / "share" / "100CANON" / "IMG_0001.jpg").is_file()
    assert (sess / "derived" / "thumbs" / "100CANON" / "IMG_0001.jpg").is_file()

    idx = (sess / "index.html").read_text("utf-8")
    idxs3 = (sess / "index.s3.html").read_text("utf-8")
    assert "Download all" in idx and "share.zip" in idx
    assert "Download all" in idxs3 and "share.zip" in idxs3
    assert "X-Amz-Signature=fake" in idxs3

    # Zip should contain share/ tree
    with zipfile.ZipFile(sess / "share.zip") as zf:
        names = set(zf.namelist())
        assert "share/100CANON/IMG_0001.jpg" in names

    # Second run should dedupe to no-op (exit 0)
    with pytest.raises(SystemExit) as e2:
        ghostroll_main(["run", "--volume", str(vol)])
    assert e2.value.code == 0

