from __future__ import annotations

import html
from pathlib import Path


def _posix(p: Path) -> str:
    return "/".join(p.parts)


def build_index_html(*, session_id: str, thumbs_dir: Path, out_path: Path) -> None:
    """
    Expects files laid out as:
      thumbs/<relpath>.jpg
      share/<relpath>.jpg
    and emits links with those relative paths.
    """
    thumbs: list[Path] = []
    if thumbs_dir.exists():
        thumbs = sorted([p for p in thumbs_dir.rglob("*") if p.is_file()])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("<!doctype html>\n")
        f.write(
            "<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<link rel=\"icon\" href=\"data:,\">"
            f"<title>{html.escape(session_id)}</title>\n"
        )
        f.write(
            "<style>"
            "body{font-family:system-ui;margin:16px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}"
            "a{display:block}"
            "img{width:100%;height:auto;border-radius:10px}"
            "</style></head><body>\n"
        )
        f.write(f"<h1>{html.escape(session_id)}</h1>\n")
        if not thumbs:
            f.write("<p>No shareable images found.</p>\n</body></html>\n")
            return

        f.write("<div class=\"grid\">\n")
        for t in thumbs:
            rel = t.relative_to(thumbs_dir)
            thumb_href = _posix(Path("thumbs") / rel)
            share_href = _posix(Path("share") / rel.with_suffix(".jpg"))
            f.write(
                f"  <a href=\"{html.escape(share_href)}\">"
                f"<img src=\"{html.escape(thumb_href)}\" loading=\"lazy\"></a>\n"
            )
        f.write("</div></body></html>\n")


def build_index_html_presigned(
    *,
    session_id: str,
    items: list[tuple[str, str]],
    out_path: Path,
) -> None:
    """
    items: list of (thumb_url, share_url) — both should be fully-qualified URLs.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        f.write("<!doctype html>\n")
        f.write(
            "<html><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<link rel=\"icon\" href=\"data:,\">"
            f"<title>{html.escape(session_id)}</title>\n"
        )
        f.write(
            "<style>"
            "body{font-family:system-ui;margin:16px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}"
            "a{display:block}"
            "img{width:100%;height:auto;border-radius:10px}"
            "</style></head><body>\n"
        )
        f.write(f"<h1>{html.escape(session_id)}</h1>\n")
        if not items:
            f.write("<p>No shareable images found.</p>\n</body></html>\n")
            return
        f.write("<div class=\"grid\">\n")
        for thumb_url, share_url in items:
            f.write(
                f"  <a href=\"{html.escape(share_url)}\">"
                f"<img src=\"{html.escape(thumb_url)}\" loading=\"lazy\"></a>\n"
            )
        f.write("</div></body></html>\n")


