from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ghostroll.status import Status, StatusWriter, get_hostname, get_ip_address


def test_status_dataclass():
    status = Status(
        state="running",
        step="process",
        message="Processing images",
        session_id="test-123",
        volume="/Volumes/test",
    )
    assert status.state == "running"
    assert status.step == "process"
    assert status.message == "Processing images"
    assert status.session_id == "test-123"
    assert status.volume == "/Volumes/test"


def test_status_writer_json(tmp_path: Path):
    json_path = tmp_path / "status.json"
    writer = StatusWriter(json_path=json_path)

    status = Status(state="running", step="scan", message="Scanning...")
    writer.write(status)

    assert json_path.exists()
    data = json.loads(json_path.read_text("utf-8"))
    assert data["state"] == "running"
    assert data["step"] == "scan"
    assert data["message"] == "Scanning..."
    assert "updated_unix" in data


def test_status_writer_atomic_write(tmp_path: Path):
    json_path = tmp_path / "status.json"
    writer = StatusWriter(json_path=json_path)

    status = Status(state="idle", step="", message="")
    writer.write(status)

    # Should not have .tmp file left behind
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_status_writer_with_image(tmp_path: Path):
    json_path = tmp_path / "status.json"
    image_path = tmp_path / "status.png"
    writer = StatusWriter(json_path=json_path, image_path=image_path, image_size=(800, 480))

    status = Status(
        state="running",
        step="process",
        message="Processing",
        hostname="test-host",
        ip="192.168.1.1",
    )
    writer.write(status)

    assert json_path.exists()
    assert image_path.exists()
    assert image_path.stat().st_size > 0


def test_status_writer_creates_directories(tmp_path: Path):
    json_path = tmp_path / "subdir" / "status.json"
    writer = StatusWriter(json_path=json_path)

    status = Status(state="idle", step="", message="")
    writer.write(status)

    assert json_path.exists()
    assert json_path.parent.exists()


def test_status_writer_counts(tmp_path: Path):
    json_path = tmp_path / "status.json"
    writer = StatusWriter(json_path=json_path)

    status = Status(
        state="running",
        step="process",
        message="Processing",
        counts={"discovered": 10, "new": 5, "processed": 3},
    )
    writer.write(status)

    data = json.loads(json_path.read_text("utf-8"))
    assert data["counts"]["discovered"] == 10
    assert data["counts"]["new"] == 5
    assert data["counts"]["processed"] == 3


def test_status_writer_url(tmp_path: Path):
    json_path = tmp_path / "status.json"
    writer = StatusWriter(json_path=json_path)

    status = Status(
        state="done",
        step="",
        message="Complete",
        url="https://example.com/share",
    )
    writer.write(status)

    data = json.loads(json_path.read_text("utf-8"))
    assert data["url"] == "https://example.com/share"


def test_get_hostname():
    hostname = get_hostname()
    assert isinstance(hostname, str)
    assert len(hostname) > 0


def test_get_ip_address():
    # This might return None in some test environments, which is fine
    ip = get_ip_address()
    if ip is not None:
        assert isinstance(ip, str)
        # Should be a valid IP format (basic check)
        parts = ip.split(".")
        assert len(parts) == 4
        assert all(0 <= int(p) <= 255 for p in parts)

