from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.qr import QrError, render_qr_ascii, write_qr_png


def test_write_qr_png(tmp_path: Path):
    out_path = tmp_path / "qr.png"
    write_qr_png(data="https://example.com/test", out_path=out_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_write_qr_png_creates_parent_dir(tmp_path: Path):
    out_path = tmp_path / "subdir" / "qr.png"
    write_qr_png(data="test data", out_path=out_path)

    assert out_path.exists()
    assert out_path.parent.exists()


def test_render_qr_ascii():
    result = render_qr_ascii("https://example.com/test")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain some block characters
    assert any(c in result for c in ["█", "▀", "▄", " "])


def test_render_qr_ascii_different_data():
    result1 = render_qr_ascii("data1")
    result2 = render_qr_ascii("data2")
    # Different data should produce different QR codes
    assert result1 != result2


def test_render_qr_ascii_empty():
    result = render_qr_ascii("")
    # Empty string should still produce something (though minimal)
    assert isinstance(result, str)


def test_qr_error_on_missing_qrcode_module(monkeypatch: pytest.MonkeyPatch):
    # Simulate missing qrcode module
    import sys

    original_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "qrcode":
            raise ImportError("No module named 'qrcode'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)

    with pytest.raises(QrError, match="QR code generation requires"):
        write_qr_png(data="test", out_path=Path("/tmp/test.png"))

    with pytest.raises(QrError, match="QR code generation requires"):
        render_qr_ascii("test")

