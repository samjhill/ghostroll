"""Web UI serves placeholder status when status.json is absent."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from ghostroll.web import GhostRollWebServer, _synthetic_status_when_missing


def test_synthetic_payload_contains_path(tmp_path: Path) -> None:
    p = tmp_path / "x" / "status.json"
    d = _synthetic_status_when_missing(p)
    assert d["state"] == "idle"
    assert d["step"] == "web"
    assert str(p.resolve()) in d["message"] or str(p.expanduser().resolve()) in d["message"]


def test_status_json_200_when_file_missing(tmp_path: Path) -> None:
    status = tmp_path / "missing" / "status.json"
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    srv = GhostRollWebServer(
        status_path=status,
        sessions_dir=sessions,
        host="127.0.0.1",
        port=0,
    )
    assert srv.start()
    try:
        assert srv.server is not None
        _, port = srv.server.server_address
        url = f"http://127.0.0.1:{port}/status.json"
        deadline = time.time() + 5.0
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as r:
                    assert r.status == 200
                    data = json.loads(r.read().decode("utf-8"))
                assert data["state"] == "idle"
                assert "No status file yet" in data["message"]
                return
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_err = e
                time.sleep(0.05)
        raise AssertionError(f"server did not respond: {last_err}")
    finally:
        srv.stop()
        if srv.thread is not None:
            srv.thread.join(timeout=5.0)
