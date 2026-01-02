from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.gallery import (
    build_index_html,
    build_index_html_from_items,
    build_index_html_loading,
    build_index_html_presigned,
)


def test_build_index_html_from_items(tmp_path: Path):
    out_path = tmp_path / "index.html"
    items = [
        ("thumbs/img1.jpg", "share/img1.jpg", "Image 1", "Camera: Canon"),
        ("thumbs/img2.jpg", "share/img2.jpg", "Image 2", "Camera: Nikon"),
    ]

    build_index_html_from_items(
        session_id="test-session",
        items=items,
        download_href="share.zip",
        out_path=out_path,
    )

    assert out_path.exists()
    content = out_path.read_text("utf-8")
    assert "test-session" in content
    assert "Image 1" in content
    assert "Image 2" in content
    assert "share.zip" in content
    assert "thumbs/img1.jpg" in content
    assert "share/img1.jpg" in content


def test_build_index_html_from_items_empty(tmp_path: Path):
    out_path = tmp_path / "index.html"

    build_index_html_from_items(
        session_id="test-session",
        items=[],
        download_href=None,
        out_path=out_path,
    )

    assert out_path.exists()
    content = out_path.read_text("utf-8")
    assert "No shareable images found" in content


def test_build_index_html_from_items_no_download(tmp_path: Path):
    out_path = tmp_path / "index.html"
    items = [("thumbs/img1.jpg", "share/img1.jpg", "Image 1", "")]

    build_index_html_from_items(
        session_id="test-session",
        items=items,
        download_href=None,
        out_path=out_path,
    )

    content = out_path.read_text("utf-8")
    assert "Download all" not in content


def test_build_index_html_presigned(tmp_path: Path):
    out_path = tmp_path / "index.html"
    items = [
        (
            "https://example.com/thumbs/img1.jpg",
            "https://example.com/share/img1.jpg",
            "Image 1",
            "Subtitle",
        )
    ]

    build_index_html_presigned(
        session_id="test-session",
        items=items,
        download_href="https://example.com/share.zip",
        out_path=out_path,
    )

    assert out_path.exists()
    content = out_path.read_text("utf-8")
    assert "https://example.com/thumbs/img1.jpg" in content
    assert "https://example.com/share/img1.jpg" in content


def test_build_index_html_from_thumbs_dir(tmp_path: Path):
    thumbs_dir = tmp_path / "thumbs" / "subdir"
    thumbs_dir.mkdir(parents=True)
    (thumbs_dir / "img1.jpg").write_text("fake")
    (thumbs_dir / "img2.jpg").write_text("fake")

    share_dir = tmp_path / "share" / "subdir"
    share_dir.mkdir(parents=True)
    (share_dir / "img1.jpg").write_text("fake")
    (share_dir / "img2.jpg").write_text("fake")

    out_path = tmp_path / "index.html"

    build_index_html(session_id="test-session", thumbs_dir=thumbs_dir, out_path=out_path)

    assert out_path.exists()
    content = out_path.read_text("utf-8")
    assert "test-session" in content
    # The function uses _posix which converts Path to forward-slash separated string
    # Since thumbs_dir is "thumbs/subdir", rel for "img1.jpg" is just "img1.jpg" (relative to thumbs_dir)
    # So hrefs are "thumbs/img1.jpg" and "share/img1.jpg"
    assert "thumbs/img1.jpg" in content
    assert "share/img1.jpg" in content


def test_build_index_html_loading(tmp_path: Path):
    out_path = tmp_path / "index.html"
    status_url = "https://example.com/status.json"

    build_index_html_loading(
        session_id="test-session",
        status_json_url=status_url,
        out_path=out_path,
        poll_seconds=2.0,
    )

    assert out_path.exists()
    content = out_path.read_text("utf-8")
    assert "test-session" in content
    assert "Upload in progress" in content
    assert status_url in content
    assert "POLL_MS" in content


def test_build_index_html_loading_creates_parent_dir(tmp_path: Path):
    out_path = tmp_path / "subdir" / "index.html"
    status_url = "https://example.com/status.json"

    build_index_html_loading(
        session_id="test-session",
        status_json_url=status_url,
        out_path=out_path,
    )

    assert out_path.exists()
    assert out_path.parent.exists()


def test_build_index_html_html_escaping(tmp_path: Path):
    out_path = tmp_path / "index.html"
    items = [
        ("thumbs/img1.jpg", "share/img1.jpg", "Image <script>alert('xss')</script>", "")
    ]

    build_index_html_from_items(
        session_id="Session <script>alert('xss')</script>",
        items=items,
        download_href=None,
        out_path=out_path,
    )

    content = out_path.read_text("utf-8")
    # User-provided content should be escaped
    assert "&lt;script&gt;" in content
    assert "Session &lt;script&gt;" in content
    # The template itself contains <script> tags for JavaScript, which is fine
    # But user-provided content in title/caption should be escaped
    assert "Image &lt;script&gt;" in content

