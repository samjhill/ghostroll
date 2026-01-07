from __future__ import annotations

import html
import json
from pathlib import Path


def _posix(p: Path) -> str:
    return "/".join(p.parts)


def _write_gallery_html(
    *,
    session_id: str,
    # list of (thumb_src, full_href, title, subtitle)
    items: list[tuple[str, str, str, str]],
    download_href: str | None = None,
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
            ".skip-link{position:absolute;top:-40px;left:0;background:var(--card);color:var(--fg);padding:8px 16px;text-decoration:none;z-index:100;border-radius:4px}"
            ".skip-link:focus{top:0}"
            ".wrap{max-width:1100px;margin:0 auto;padding:max(18px,env(safe-area-inset-top)) max(18px,env(safe-area-inset-right)) max(18px,env(safe-area-inset-bottom)) max(18px,env(safe-area-inset-left))}"
            ".top{display:flex;align-items:baseline;gap:12px;justify-content:space-between;margin-bottom:14px}"
            ".title{font-size:18px;font-weight:700;letter-spacing:.2px;margin:0}"
            ".meta{color:var(--muted);font-size:13px}"
            ".btn{display:inline-flex;align-items:center;gap:6px;padding:8px 10px;border-radius:999px;"
            "border:1px solid var(--border);background:var(--card);text-decoration:none;color:inherit}"
            ".btn:hover{filter:brightness(1.05)}"
            ".btn:focus{outline:2px solid #3b82f6;outline-offset:2px}"
            ".grid{display:flex;flex-direction:column;gap:12px}"
            ".tile{position:relative;display:block;border-radius:var(--radius);overflow:hidden;background:var(--card);"
            "border:1px solid var(--border);box-shadow:var(--shadow);transform:translateZ(0);width:100%;"
            "transition:transform 0.2s,box-shadow 0.2s}"
            ".tile:hover{transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,0,0,.4)}"
            ".tile:focus{outline:2px solid #3b82f6;outline-offset:2px}"
            ".tile img{display:block;width:100%;height:auto;object-fit:contain;background:linear-gradient(90deg,#1a1a1a 25%,#2a2a2a 50%,#1a1a1a 75%);background-size:200% 100%;animation:shimmer 1.5s infinite}"
            "@keyframes shimmer{0%{background-position:-200% 0}100%{background-position:200% 0}}"
            ".tile img[src]{animation:none;background:#0a0a0a}"
            ".empty{padding:22px;border:1px dashed var(--border);border-radius:var(--radius);color:var(--muted);text-align:center}"
            "/* lightbox */"
            ".lb{position:fixed;inset:0;display:none;align-items:center;justify-content:center;background:rgba(0,0,0,.78);z-index:50;height:100dvh}"
            ".lb.open{display:flex}"
            ".lb-inner{width:min(92vw,1200px);height:min(88vh,900px);display:flex;flex-direction:column;gap:10px}"
            ".lb-bar{display:flex;align-items:center;justify-content:space-between;color:#fff;font-size:13px;flex-wrap:wrap;gap:12px}"
            ".lb-info{display:flex;flex-direction:column;gap:4px}"
            ".lb-cap{font-weight:600}"
            ".lb-sub{opacity:.8;font-size:12px}"
            ".lb-counter{opacity:.8;font-size:12px;margin-top:4px}"
            ".lb-controls{display:flex;gap:8px;flex-wrap:wrap}"
            ".lb-btn{appearance:none;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.25);color:#fff;"
            "padding:8px 10px;border-radius:10px;cursor:pointer;transition:background 0.2s}"
            ".lb-btn:hover{background:rgba(0,0,0,.4)}"
            ".lb-btn:focus{outline:2px solid #fff;outline-offset:2px}"
            ".lb-img{flex:1;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:14px;position:relative}"
            ".lb-img img{max-width:100%;max-height:100%;border-radius:14px;background:#000}"
            ".lb-loading{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:40px;height:40px;border:4px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;display:none}"
            ".lb-loading.active{display:block}"
            "@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}"
            ".lb-img img.error{opacity:.5}"
            "@media (max-width:600px){"
            ".top{flex-direction:column;gap:8px}"
            ".meta{font-size:12px}"
            ".lb-btn{padding:12px 16px;min-height:44px;font-size:14px}"
            ".lb-bar{flex-direction:column;align-items:stretch}"
            ".lb-controls{justify-content:space-between;width:100%}"
            "}"
            "</style>\n"
        )
        f.write("</head><body>\n")
        f.write("<a href=\"#grid\" class=\"skip-link\">Skip to gallery</a>\n")
        f.write("<div class=\"wrap\">\n")
        f.write("<div class=\"top\">")
        f.write(f"<h1 class=\"title\">{html.escape(session_id)}</h1>")
        f.write("<div class=\"meta\">")
        f.write(f"{count} image{'s' if count != 1 else ''}")
        if download_href:
            f.write(
                f" · <a class=\"btn\" href=\"{html.escape(download_href)}\">Download all</a>"
            )
        f.write("</div>")
        f.write("</div>\n")

        if not items:
            f.write("<div class=\"empty\">No shareable images found.</div>\n")
        else:
            f.write("<div class=\"grid\" id=\"grid\">\n")
            for i, (thumb_src, full_href, title, subtitle) in enumerate(items):
                # Generate better alt text: use subtitle if available, otherwise descriptive text
                alt_text = subtitle if subtitle else (f"Gallery image {i + 1}" if not title or "/" in title or "\\" in title else title)
                f.write(
                    "<a class=\"tile\" href=\"{full}\" data-full=\"{full}\" data-cap=\"{cap}\" data-sub=\"{sub}\" "
                    "data-idx=\"{idx}\" aria-label=\"Open image {num}\">"
                    "<img src=\"{thumb}\" loading=\"lazy\" decoding=\"async\" alt=\"{alt}\">"
                    "</a>\n".format(
                        full=html.escape(full_href),
                        thumb=html.escape(thumb_src),
                        cap=html.escape(title),
                        sub=html.escape(subtitle),
                        alt=html.escape(alt_text),
                        idx=i,
                        num=i + 1,
                    )
                )
            f.write("</div>\n")

        # Lightbox shell + JS
        f.write(
            "<div class=\"lb\" id=\"lb\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Image viewer\">"
            "<div class=\"lb-inner\">"
            "<div class=\"lb-bar\">"
            "<div class=\"lb-info\">"
            "<div class=\"lb-cap\" id=\"lbCap\"></div>"
            "<div class=\"lb-sub\" id=\"lbSub\"></div>"
            "<div class=\"lb-counter\" id=\"lbCounter\"></div>"
            "</div>"
            "<div class=\"lb-controls\">"
            "<button class=\"lb-btn\" id=\"prevBtn\" type=\"button\" aria-label=\"Previous image\">← Prev</button>"
            "<button class=\"lb-btn\" id=\"nextBtn\" type=\"button\" aria-label=\"Next image\">Next →</button>"
            "<a class=\"lb-btn\" id=\"downloadBtn\" href=\"#\" aria-label=\"Download image\" style=\"display:none;text-decoration:none\">↓ Download</a>"
            "<button class=\"lb-btn\" id=\"closeBtn\" type=\"button\" aria-label=\"Close lightbox\">Esc ✕</button>"
            "</div></div>"
            "<div class=\"lb-img\">"
            "<div class=\"lb-loading\" id=\"lbLoading\"></div>"
            "<img id=\"lbImg\" alt=\"\">"
            "</div>"
            "</div></div>\n"
        )
        f.write(
            "<script>"
            "(() => {"
            "const lb=document.getElementById('lb');"
            "const img=document.getElementById('lbImg');"
            "const cap=document.getElementById('lbCap');"
            "const sub=document.getElementById('lbSub');"
            "const counter=document.getElementById('lbCounter');"
            "const loading=document.getElementById('lbLoading');"
            "const downloadBtn=document.getElementById('downloadBtn');"
            "const closeBtn=document.getElementById('closeBtn');"
            "const prevBtn=document.getElementById('prevBtn');"
            "const nextBtn=document.getElementById('nextBtn');"
            "const tiles=[...document.querySelectorAll('#grid .tile')];"
            "let idx=-1;"
            "let lastFocusedElement=null;"
            "if(!lb||!img||!cap||!sub||!counter||!loading) return;"
            "function preloadAdjacent(){"
            "if(idx+1<tiles.length){const nextImg=new Image();nextImg.src=tiles[idx+1].dataset.full;}"
            "if(idx-1>=0){const prevImg=new Image();prevImg.src=tiles[idx-1].dataset.full;}"
            "}"
            "function updateCounter(){"
            "if(tiles.length>0){counter.textContent=(idx+1)+' / '+tiles.length;}else{counter.textContent='';}"
            "}"
            "function showLoading(){if(loading) loading.classList.add('active');}"
            "function hideLoading(){if(loading) loading.classList.remove('active');}"
            "function openAt(i){"
            "if(!tiles.length) return;"
            "lastFocusedElement=document.activeElement;"
            "idx=(i+tiles.length)%tiles.length;"
            "const t=tiles[idx];"
            "showLoading();"
            "img.onload=function(){hideLoading();img.classList.remove('error');}"
            "img.onerror=function(){hideLoading();img.classList.add('error');img.alt='Failed to load image';}"
            "img.src=t.dataset.full;"
            "img.alt=t.dataset.cap||'';"
            "cap.textContent=t.dataset.cap||'';"
            "sub.textContent=t.dataset.sub||'';"
            "updateCounter();"
            "if(downloadBtn){downloadBtn.style.display='inline-flex';downloadBtn.href=t.dataset.full;downloadBtn.download='';}"
            "lb.classList.add('open');"
            "document.body.style.overflow='hidden';"
            "preloadAdjacent();"
            "setTimeout(()=>{if(closeBtn) closeBtn.focus();},100);"
            "}"
            "function close(){"
            "lb.classList.remove('open');"
            "document.body.style.overflow='';"
            "idx=-1;"
            "img.src='';"
            "hideLoading();"
            "if(lastFocusedElement){lastFocusedElement.focus();lastFocusedElement=null;}"
            "}"
            "function next(){openAt(idx+1)}"
            "function prev(){openAt(idx-1)}"
            "let touchStartX=0;"
            "let touchStartY=0;"
            "lb.addEventListener('touchstart',(e)=>{"
            "touchStartX=e.touches[0].clientX;"
            "touchStartY=e.touches[0].clientY;"
            "},{passive:true});"
            "lb.addEventListener('touchend',(e)=>{"
            "if(!lb.classList.contains('open')) return;"
            "const touchEndX=e.changedTouches[0].clientX;"
            "const touchEndY=e.changedTouches[0].clientY;"
            "const deltaX=touchStartX-touchEndX;"
            "const deltaY=touchStartY-touchEndY;"
            "if(Math.abs(deltaX)>Math.abs(deltaY)&&Math.abs(deltaX)>50){"
            "if(deltaX>0) next();"
            "else prev();"
            "}"
            "},{passive:true});"
            "tiles.forEach((t) => {"
            "t.addEventListener('click',(e)=>{e.preventDefault();openAt(parseInt(t.dataset.idx||'0',10));});"
            "});"
            "if(closeBtn) closeBtn.addEventListener('click', close);"
            "if(nextBtn) nextBtn.addEventListener('click', next);"
            "if(prevBtn) prevBtn.addEventListener('click', prev);"
            "if(downloadBtn) downloadBtn.addEventListener('click',(e)=>{e.preventDefault();if(downloadBtn.href&&downloadBtn.href!='#'){window.open(downloadBtn.href,'_blank');}});"
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

    items: list[tuple[str, str, str, str]] = []
    for t in thumbs:
        rel = t.relative_to(thumbs_dir)
        thumb_href = _posix(Path("thumbs") / rel)
        share_href = _posix(Path("share") / rel.with_suffix(".jpg"))
        title = rel.as_posix()
        items.append((thumb_href, share_href, title, ""))

    _write_gallery_html(session_id=session_id, items=items, out_path=out_path)


def build_index_html_from_items(
    *,
    session_id: str,
    items: list[tuple[str, str, str, str]],
    download_href: str | None,
    out_path: Path,
) -> None:
    _write_gallery_html(session_id=session_id, items=items, download_href=download_href, out_path=out_path)


def build_index_html_presigned(
    *,
    session_id: str,
    items: list[tuple[str, str, str, str]],
    download_href: str | None = None,
    out_path: Path,
) -> None:
    """
    items: list of (thumb_url, share_url, title, subtitle) — URLs should be fully-qualified.
    """
    _write_gallery_html(session_id=session_id, items=items, download_href=download_href, out_path=out_path)


def build_index_html_loading(
    *,
    session_id: str,
    status_json_url: str,
    out_path: Path,
    poll_seconds: float = 2.0,
) -> None:
    """
    Writes a minimal gallery page that shows an "upload in progress..." message and polls a
    presigned status JSON URL. When uploading is complete, it reloads the page (so if the
    backing S3 key was overwritten with the final gallery, the user sees it automatically).

    Expected status JSON shape (extra fields ignored):
      {"uploading": true|false, "message": "...optional..."}
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    poll_ms = max(500, int(poll_seconds * 1000))
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
            ".wrap{max-width:900px;margin:0 auto;padding:18px}"
            ".top{display:flex;align-items:baseline;gap:12px;justify-content:space-between;margin-bottom:14px}"
            ".title{font-size:18px;font-weight:700;letter-spacing:.2px;margin:0}"
            ".meta{color:var(--muted);font-size:13px}"
            ".card{padding:18px;border-radius:var(--radius);border:1px solid var(--border);background:var(--card);box-shadow:var(--shadow)}"
            ".msg{font-size:15px;font-weight:650;margin:0 0 8px 0}"
            ".sub{color:var(--muted);font-size:13px;margin:0}"
            ".dot{display:inline-block;width:8px;height:8px;border-radius:999px;background:#f59e0b;margin-right:8px;vertical-align:baseline;box-shadow:0 0 0 3px rgba(245,158,11,.18)}"
            "</style>\n"
        )
        f.write("</head><body>\n")
        f.write("<div class=\"wrap\">\n")
        f.write("<div class=\"top\">")
        f.write(f"<h1 class=\"title\">{html.escape(session_id)}</h1>")
        f.write("<div class=\"meta\">Gallery</div>")
        f.write("</div>\n")
        f.write("<div class=\"card\" id=\"card\">")
        f.write("<p class=\"msg\" id=\"msg\"><span class=\"dot\"></span>Upload in progress…</p>")
        f.write("<p class=\"sub\" id=\"sub\">This page will auto-refresh when the gallery is ready.</p>")
        f.write("</div>\n")
        f.write("</div>\n")

        # Poll status JSON; reload when uploading is complete.
        f.write("<script>\n")
        f.write(f"const STATUS_URL = {json.dumps(status_json_url)};\n")
        f.write(f"const POLL_MS = {poll_ms};\n")
        f.write(
            "const msgEl=document.getElementById('msg');\n"
            "const subEl=document.getElementById('sub');\n"
            "let stopped=false;\n"
            "async function tick(){\n"
            "  if(stopped) return;\n"
            "  try{\n"
            "    const res=await fetch(STATUS_URL,{cache:'no-store'});\n"
            "    if(!res.ok) throw new Error('status fetch failed: '+res.status);\n"
            "    const j=await res.json();\n"
            "    const uploading=(j && typeof j.uploading==='boolean') ? j.uploading : true;\n"
            "    if(j && j.message && subEl) subEl.textContent=j.message;\n"
            "    if(!uploading){\n"
            "      stopped=true;\n"
            "      if(msgEl) msgEl.textContent='Upload complete. Loading gallery…';\n"
            "      setTimeout(()=>{ try{ window.location.reload(); }catch(e){} }, 250);\n"
            "    }\n"
            "  }catch(e){\n"
            "    // Keep the optimistic default; transient errors shouldn't blank the UI.\n"
            "  }\n"
            "}\n"
            "tick();\n"
            "setInterval(tick, POLL_MS);\n"
        )
        f.write("</script>\n")
        f.write("</body></html>\n")


