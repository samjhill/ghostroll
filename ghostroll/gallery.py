from __future__ import annotations

import html
from pathlib import Path


def _posix(p: Path) -> str:
    return "/".join(p.parts)


def _write_gallery_html(
    *,
    session_id: str,
    # list of (thumb_src, full_href, caption)
    items: list[tuple[str, str, str]],
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = len(items)
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
            ":root{color-scheme:light dark;"
            "--bg:#0b0f14;--fg:#e7edf5;--muted:#9aa7b5;--card:#101826;--border:#1a2a3d;"
            "--shadow:0 10px 30px rgba(0,0,0,.35);--radius:14px}"
            "@media (prefers-color-scheme:light){"
            ":root{--bg:#f6f8fb;--fg:#111827;--muted:#5b6472;--card:#ffffff;--border:#e6e9ef;"
            "--shadow:0 10px 30px rgba(17,24,39,.08)}}"
            "html,body{height:100%}"
            "body{margin:0;background:var(--bg);color:var(--fg);font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial}"
            ".wrap{max-width:1100px;margin:0 auto;padding:18px}"
            ".top{display:flex;align-items:baseline;gap:12px;justify-content:space-between;margin-bottom:14px}"
            ".title{font-size:18px;font-weight:700;letter-spacing:.2px;margin:0}"
            ".meta{color:var(--muted);font-size:13px}"
            ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}"
            ".tile{position:relative;display:block;border-radius:var(--radius);overflow:hidden;background:var(--card);"
            "border:1px solid var(--border);box-shadow:var(--shadow);transform:translateZ(0)}"
            ".tile:focus{outline:2px solid #3b82f6;outline-offset:2px}"
            ".tile img{display:block;width:100%;height:170px;object-fit:cover;background:#0a0a0a}"
            ".cap{position:absolute;left:8px;right:8px;bottom:8px;padding:6px 8px;border-radius:10px;"
            "background:rgba(0,0,0,.55);color:#fff;font-size:12px;line-height:1.2;"
            "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
            "@media (prefers-color-scheme:light){.cap{background:rgba(17,24,39,.55)}}"
            ".empty{padding:22px;border:1px dashed var(--border);border-radius:var(--radius);color:var(--muted)}"
            "/* lightbox */"
            ".lb{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.78);z-index:50}"
            ".lb.open{display:flex}"
            ".lb-inner{width:min(92vw,1200px);height:min(88vh,900px);display:flex;flex-direction:column;gap:10px}"
            ".lb-bar{display:flex;align-items:center;justify-content:space-between;color:#fff;font-size:13px}"
            ".lb-btn{appearance:none;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.25);color:#fff;"
            "padding:8px 10px;border-radius:10px;cursor:pointer}"
            ".lb-btn:hover{background:rgba(0,0,0,.4)}"
            ".lb-img{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:14px}"
            ".lb-img img{max-width:100%;max-height:100%;border-radius:14px;background:#000}"
            "</style>\n"
        )
        f.write("</head><body>\n")
        f.write("<div class=\"wrap\">\n")
        f.write("<div class=\"top\">")
        f.write(f"<h1 class=\"title\">{html.escape(session_id)}</h1>")
        f.write(f"<div class=\"meta\">{count} image{'s' if count != 1 else ''}</div>")
        f.write("</div>\n")

        if not items:
            f.write("<div class=\"empty\">No shareable images found.</div>\n")
        else:
            f.write("<div class=\"grid\" id=\"grid\">\n")
            for i, (thumb_src, full_href, caption) in enumerate(items):
                f.write(
                    "<a class=\"tile\" href=\"{full}\" data-full=\"{full}\" data-cap=\"{cap}\" "
                    "data-idx=\"{idx}\" aria-label=\"Open image\">"
                    "<img src=\"{thumb}\" loading=\"lazy\" decoding=\"async\" alt=\"{cap}\">"
                    "<div class=\"cap\">{cap}</div>"
                    "</a>\n".format(
                        full=html.escape(full_href),
                        thumb=html.escape(thumb_src),
                        cap=html.escape(caption),
                        idx=i,
                    )
                )
            f.write("</div>\n")

        # Lightbox shell + JS
        f.write(
            "<div class=\"lb\" id=\"lb\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Image viewer\">"
            "<div class=\"lb-inner\">"
            "<div class=\"lb-bar\">"
            "<div id=\"lbCap\"></div>"
            "<div style=\"display:flex;gap:8px\">"
            "<button class=\"lb-btn\" id=\"prevBtn\" type=\"button\">← Prev</button>"
            "<button class=\"lb-btn\" id=\"nextBtn\" type=\"button\">Next →</button>"
            "<button class=\"lb-btn\" id=\"closeBtn\" type=\"button\">Esc ✕</button>"
            "</div></div>"
            "<div class=\"lb-img\"><img id=\"lbImg\" alt=\"\"></div>"
            "</div></div>\n"
        )
        f.write(
            "<script>"
            "(() => {"
            "const lb=document.getElementById('lb');"
            "const img=document.getElementById('lbImg');"
            "const cap=document.getElementById('lbCap');"
            "const tiles=[...document.querySelectorAll('#grid .tile')];"
            "let idx=-1;"
            "function openAt(i){"
            "if(!tiles.length) return;"
            "idx=(i+tiles.length)%tiles.length;"
            "const t=tiles[idx];"
            "img.src=t.dataset.full;"
            "img.alt=t.dataset.cap||'';"
            "cap.textContent=t.dataset.cap||'';"
            "lb.classList.add('open');"
            "document.body.style.overflow='hidden';"
            "}"
            "function close(){lb.classList.remove('open');document.body.style.overflow='';idx=-1;img.src='';}"
            "function next(){openAt(idx+1)}"
            "function prev(){openAt(idx-1)}"
            "tiles.forEach((t) => {"
            "t.addEventListener('click',(e)=>{e.preventDefault();openAt(parseInt(t.dataset.idx||'0',10));});"
            "});"
            "document.getElementById('closeBtn')?.addEventListener('click', close);"
            "document.getElementById('nextBtn')?.addEventListener('click', next);"
            "document.getElementById('prevBtn')?.addEventListener('click', prev);"
            "lb.addEventListener('click',(e)=>{if(e.target===lb) close();});"
            "document.addEventListener('keydown',(e)=>{"
            "if(!lb.classList.contains('open')) return;"
            "if(e.key==='Escape') close();"
            "else if(e.key==='ArrowRight') next();"
            "else if(e.key==='ArrowLeft') prev();"
            "});"
            "})();"
            "</script>\n"
        )

        f.write("</div></body></html>\n")


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

    items: list[tuple[str, str, str]] = []
    for t in thumbs:
        rel = t.relative_to(thumbs_dir)
        thumb_href = _posix(Path("thumbs") / rel)
        share_href = _posix(Path("share") / rel.with_suffix(".jpg"))
        caption = rel.name
        items.append((thumb_href, share_href, caption))

    _write_gallery_html(session_id=session_id, items=items, out_path=out_path)


def build_index_html_presigned(
    *,
    session_id: str,
    items: list[tuple[str, str]],
    out_path: Path,
) -> None:
    """
    items: list of (thumb_url, share_url) — both should be fully-qualified URLs.
    """
    ui_items: list[tuple[str, str, str]] = []
    for i, (thumb_url, share_url) in enumerate(items):
        ui_items.append((thumb_url, share_url, f"Image {i+1}"))
    _write_gallery_html(session_id=session_id, items=ui_items, out_path=out_path)


