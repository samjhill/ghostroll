from __future__ import annotations

import html
import json
from pathlib import Path


def _posix(p: Path) -> str:
    return "/".join(p.parts)


def _effective_gallery_share_url(*, share_page_url: str | None, out_path: Path) -> str | None:
    """Presigned gallery page URL from caller, else first line of sibling ``share.txt`` if it looks like HTTP(S)."""
    u = (share_page_url or "").strip()
    if u.startswith("https://") or u.startswith("http://"):
        return u
    try:
        st = out_path.parent / "share.txt"
        if st.exists():
            line = st.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
            if line.startswith("https://") or line.startswith("http://"):
                return line
    except Exception:
        pass
    return None


def _write_gallery_html(
    *,
    session_id: str,
    # list of:
    # - (thumb_src, full_href, title, subtitle)
    # - (thumb_src, full_href, title, subtitle, enhanced_href)
    # - (thumb_src, full_href, title, subtitle, enhanced_href, tags_href)
    # enhanced_href/tags_href can be None if not available
    items: list[tuple],
    download_href: str | None = None,
    out_path: Path,
    share_page_url: str | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = len(items)
    share_link = _effective_gallery_share_url(share_page_url=share_page_url, out_path=out_path)
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
            "transition:transform 0.2s,box-shadow 0.2s;cursor:pointer}"
            ".tile:hover{transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,0,0,.4)}"
            ".tile:focus{outline:2px solid #3b82f6;outline-offset:2px}"
            ".tile:focus:not(:focus-visible){outline:none}"
            ".tile:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}"
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
            ".lb-tags{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:6px}"
            ".chip{appearance:none;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.25);color:#fff;"
            "padding:6px 10px;border-radius:999px;cursor:pointer;font-size:12px;font-family:inherit;line-height:1}"
            ".chip:hover{background:rgba(0,0,0,.4)}"
            ".chip:focus{outline:2px solid #fff;outline-offset:2px}"
            ".lb-counter{opacity:.8;font-size:12px;margin-top:4px}"
            ".lb-controls{display:flex;gap:8px;flex-wrap:wrap}"
            ".lb-btn{appearance:none;border:1px solid rgba(255,255,255,.22);background:rgba(0,0,0,.25);color:#fff;"
            "padding:8px 10px;border-radius:10px;cursor:pointer;transition:background 0.2s;font-size:13px;font-family:inherit}"
            ".lb-btn:hover{background:rgba(0,0,0,.4)}"
            ".lb-btn:focus{outline:2px solid #fff;outline-offset:2px}"
            ".lb-btn:active{transform:scale(0.95)}"
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
            "@media (prefers-reduced-motion:reduce){"
            "*{animation-duration:0.01ms!important;animation-iteration-count:1!important;transition-duration:0.01ms!important}"
            "}"
            "/* Improved accessibility */"
            "a:focus-visible,button:focus-visible{outline:2px solid #3b82f6;outline-offset:2px}"
            "a:focus:not(:focus-visible){outline:none}"
            ".qr-section{padding:18px 0;border-top:1px solid var(--border);margin-top:18px;display:flex;flex-direction:column;align-items:center;gap:12px}"
            ".qr-title{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;font-weight:600}"
            ".qr-code{width:160px;height:160px;border-radius:var(--radius);border:2px solid var(--border);padding:8px;background:#ffffff;box-shadow:var(--shadow);display:block;transition:transform 0.2s,box-shadow 0.2s}"
            ".qr-code:hover{transform:translateY(-2px);box-shadow:0 12px 40px rgba(0,0,0,.4)}"
            ".qr-code img{width:100%;height:100%;object-fit:contain;display:block}"
            ".qr-hint{font-size:12px;color:var(--muted);text-align:center}"
            "@media (max-width:600px){"
            ".qr-code{width:140px;height:140px}"
            "}"
            ".filter{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0 14px}"
            ".filter label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:700}"
            ".filter input{flex:1;min-width:220px;max-width:520px;border-radius:999px;border:1px solid var(--border);"
            "background:var(--card);color:var(--fg);padding:10px 12px;font-size:14px}"
            ".filter input:focus{outline:2px solid #3b82f6;outline-offset:2px}"
            ".filter .status{font-size:12px;color:var(--muted)}"
            ".tag-panel{border:1px solid var(--border);border-radius:var(--radius);background:var(--card);"
            "box-shadow:var(--shadow);margin:0 0 16px;overflow:hidden}"
            ".tag-panel>summary{list-style:none;cursor:pointer;padding:12px 14px;font-size:14px;font-weight:600;"
            "color:var(--fg);user-select:none;display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}"
            ".tag-panel>summary::-webkit-details-marker{display:none}"
            ".tag-panel .tag-panel-hint{font-weight:400;color:var(--muted);font-size:12px}"
            ".tag-panel[open]>summary{border-bottom:1px solid var(--border)}"
            ".tag-panel-body{padding:12px 14px 14px}"
            ".tag-panel-body .filter{margin-top:0}"
            ".tag-strip{margin:0;display:flex;flex-direction:column;gap:10px}"
            ".tag-strip-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}"
            ".tag-strip-label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;font-weight:700}"
            ".tag-strip-inner{display:flex;flex-wrap:wrap;gap:8px;align-items:center}"
            "button.filter-chip{font-size:13px;padding:7px 12px;border-radius:999px;cursor:pointer;font-family:inherit;line-height:1.2}"
            "button.filter-chip.is-active{border-color:#3b82f6;background:rgba(59,130,246,.18);color:var(--fg)}"
            "@media (prefers-color-scheme:light){"
            "button.filter-chip.is-active{background:rgba(59,130,246,.12)}"
            "}"
            ".share-short{margin-bottom:14px;padding:12px 14px;border-radius:var(--radius);border:1px solid var(--border);"
            "background:var(--card);box-shadow:var(--shadow)}"
            ".share-short .share-label{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;"
            "letter-spacing:.5px;font-weight:700;margin-bottom:8px}"
            ".share-short .share-row{display:flex;gap:8px;align-items:stretch;flex-wrap:wrap}"
            ".share-short input#ghostrollShareUrl{flex:1;min-width:0;min-height:40px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
            "font-size:12px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--bg-secondary);color:var(--fg)}"
            ".share-short .share-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}"
            "</style>\n"
        )
        f.write("</head><body>\n")
        f.write("<a href=\"#grid\" class=\"skip-link\">Skip to gallery</a>\n")
        f.write("<div class=\"wrap\">\n")
        if share_link:
            esc = html.escape(share_link, quote=True)
            f.write('<div class="share-short" role="region" aria-label="Share link">\n')
            f.write('<span class="share-label">Share this gallery</span>\n')
            f.write('<div class="share-row">\n')
            f.write(
                f'<input id="ghostrollShareUrl" type="text" readonly value="{esc}" '
                'aria-label="Gallery share URL" onclick="this.select()">\n'
            )
            f.write('<div class="share-actions">\n')
            f.write(
                f'<a class="btn" href="{html.escape(share_link)}" target="_blank" rel="noopener noreferrer">Open</a>\n'
            )
            f.write(
                '<button class="btn" type="button" id="copyShareUrlBtn" '
                'aria-label="Copy gallery link to clipboard">Copy link</button>\n'
            )
            f.write("</div>\n</div>\n</div>\n")

        f.write("<div class=\"top\">")
        f.write(f"<h1 class=\"title\">{html.escape(session_id)}</h1>")
        f.write("<div class=\"meta\">")
        f.write(f"{count} image{'s' if count != 1 else ''}")
        if download_href:
            f.write(
                f" · <a class=\"btn\" href=\"{html.escape(download_href)}\">Download all</a>"
            )
        # Check if any images have enhanced versions
        has_enhanced = any(item[4] for item in items if len(item) > 4)
        # Check if any images have tags sidecars
        has_tags = any(item[5] for item in items if len(item) > 5)
        if has_enhanced:
            f.write(
                ' · <button class="btn" id="enhanceToggle" type="button" aria-label="Toggle enhanced images">'
                '<span id="enhanceToggleText">✨ Enhanced</span>'
                '</button>'
            )
        f.write("</div>")
        f.write("</div>\n")

        if has_tags:
            f.write(
                "<details class=\"tag-panel\" id=\"tagPanel\">"
                "<summary><span>Tags &amp; filter</span>"
                "<span class=\"tag-panel-hint\">Show / hide</span></summary>"
                "<div class=\"tag-panel-body\">"
                "<div class=\"filter\">"
                "<label for=\"tagFilter\">Filter</label>"
                "<input id=\"tagFilter\" type=\"search\" placeholder=\"Filter by tags or people (e.g. Person 1)\" autocomplete=\"off\">"
                "<div class=\"status\" id=\"tagFilterStatus\" aria-live=\"polite\"></div>"
                "</div>"
                "<div class=\"tag-strip\" id=\"tagStrip\" role=\"region\" aria-label=\"Filter by tag\">"
                "<div class=\"tag-strip-head\">"
                "<span class=\"tag-strip-label\">Tags</span>"
                "<button type=\"button\" class=\"btn filter-chip is-active\" id=\"tagChipAll\" aria-pressed=\"true\">All</button>"
                "</div>"
                "<div class=\"tag-strip-inner\" id=\"tagStripInner\"></div>"
                "</div>"
                "</div>"
                "</details>\n"
            )
        
        # Check if QR code exists in the same directory as the output file
        qr_code_path = out_path.parent / "share-qr.png"
        qr_code_url = None
        if qr_code_path.exists() and qr_code_path.is_file() and qr_code_path.stat().st_size > 0:
            qr_code_url = "share-qr.png"

        if not items:
            f.write("<div class=\"empty\">No shareable images found.</div>\n")
        else:
            f.write("<div class=\"grid\" id=\"grid\">\n")
            for i, item in enumerate(items):
                # Back-compat: accept 4/5/6-tuples
                thumb_src, full_href, title, subtitle = item[:4]
                enhanced_href = item[4] if len(item) >= 5 else None
                tags_href = item[5] if len(item) >= 6 else None
                
                # Generate better alt text: use subtitle if available, otherwise descriptive text
                alt_text = subtitle if subtitle else (f"Gallery image {i + 1}" if not title or "/" in title or "\\" in title else title)
                
                # Build data attributes - include both normal and enhanced URLs
                data_attrs = f'data-full="{html.escape(full_href)}"'
                if enhanced_href:
                    data_attrs += f' data-enhanced="{html.escape(enhanced_href)}"'
                if tags_href:
                    data_attrs += f' data-tags="{html.escape(tags_href)}"'
                
                f.write(
                    "<a class=\"tile\" href=\"{full}\" {data_attrs} data-cap=\"{cap}\" data-sub=\"{sub}\" "
                    "data-idx=\"{idx}\" aria-label=\"Open image {num}\">"
                    "<img src=\"{thumb}\" loading=\"lazy\" decoding=\"async\" alt=\"{alt}\">"
                    "</a>\n".format(
                        full=html.escape(full_href),
                        data_attrs=data_attrs,
                        thumb=html.escape(thumb_src),
                        cap=html.escape(title),
                        sub=html.escape(subtitle),
                        alt=html.escape(alt_text),
                        idx=i,
                        num=i + 1,
                    )
                )
            f.write("</div>\n")
        
        # Add QR code section if available
        if qr_code_url:
            # Try to get the URL from share.txt if available
            share_txt_path = out_path.parent / "share.txt"
            qr_link_url = None
            if share_txt_path.exists():
                try:
                    share_url = share_txt_path.read_text(encoding="utf-8").strip()
                    if share_url:
                        qr_link_url = share_url
                except Exception:
                    pass
            # Fallback to download_href or just show QR without link
            if not qr_link_url and download_href:
                qr_link_url = download_href
            
            f.write('<div class="qr-section">\n')
            f.write('<div class="qr-title">Scan to Open Gallery</div>\n')
            if qr_link_url:
                f.write(f'<a href="{html.escape(qr_link_url)}" target="_blank" class="qr-code" aria-label="QR code for gallery link">\n')
            else:
                f.write('<div class="qr-code">\n')
            f.write(f'<img src="{html.escape(qr_code_url)}" alt="QR code" loading="lazy">\n')
            if qr_link_url:
                f.write('</a>\n')
            else:
                f.write('</div>\n')
            f.write('<div class="qr-hint">Point your phone camera at the code</div>\n')
            f.write('</div>\n')

        # Lightbox shell + JS
        f.write(
            "<div class=\"lb\" id=\"lb\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Image viewer\">"
            "<div class=\"lb-inner\">"
            "<div class=\"lb-bar\">"
            "<div class=\"lb-info\">"
            "<div class=\"lb-cap\" id=\"lbCap\"></div>"
            "<div class=\"lb-sub\" id=\"lbSub\"></div>"
            "<div class=\"lb-tags\" id=\"lbTags\"></div>"
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
            "const copyShareUrlBtn=document.getElementById('copyShareUrlBtn');"
            "const ghostrollShareUrlInput=document.getElementById('ghostrollShareUrl');"
            "if(copyShareUrlBtn&&ghostrollShareUrlInput){"
            "copyShareUrlBtn.addEventListener('click',async()=>{"
            "const t=ghostrollShareUrlInput.value;"
            "try{"
            "await navigator.clipboard.writeText(t);"
            "copyShareUrlBtn.textContent='Copied';"
            "setTimeout(()=>{copyShareUrlBtn.textContent='Copy link';},1800);"
            "}catch(e){"
            "try{"
            "ghostrollShareUrlInput.select();"
            "document.execCommand('copy');"
            "copyShareUrlBtn.textContent='Copied';"
            "setTimeout(()=>{copyShareUrlBtn.textContent='Copy link';},1800);"
            "}catch(_){"
            "alert('Select the link and copy manually');"
            "}"
            "}"
            "});"
            "}"
            "const lb=document.getElementById('lb');"
            "const img=document.getElementById('lbImg');"
            "const cap=document.getElementById('lbCap');"
            "const sub=document.getElementById('lbSub');"
            "const tags=document.getElementById('lbTags');"
            "const counter=document.getElementById('lbCounter');"
            "const loading=document.getElementById('lbLoading');"
            "const downloadBtn=document.getElementById('downloadBtn');"
            "const closeBtn=document.getElementById('closeBtn');"
            "const prevBtn=document.getElementById('prevBtn');"
            "const nextBtn=document.getElementById('nextBtn');"
            "const tiles=[...document.querySelectorAll('#grid .tile')];"
            "const filterInput=document.getElementById('tagFilter');"
            "const filterStatus=document.getElementById('tagFilterStatus');"
            "const tagStrip=document.getElementById('tagStrip');"
            "const tagStripInner=document.getElementById('tagStripInner');"
            "const tagChipAll=document.getElementById('tagChipAll');"
            "let idx=-1;"
            "let lastFocusedElement=null;"
            "const enhanceToggle=document.getElementById('enhanceToggle');"
            "const enhanceToggleText=document.getElementById('enhanceToggleText');"
            "let useEnhanced=true;"
            "function updateEnhanceToggle(){"
            "  if(!enhanceToggleText) return;"
            "  enhanceToggleText.textContent=useEnhanced?'✨ Enhanced':'📷 Original';"
            "  if(enhanceToggle) enhanceToggle.setAttribute('aria-pressed',useEnhanced.toString());"
            "}"
            "if(enhanceToggle&&enhanceToggleText){"
            "  const saved=localStorage.getItem('ghostrollUseEnhanced');"
            "  if(saved!==null)useEnhanced=saved==='true';"
            "  updateEnhanceToggle();"
            "  enhanceToggle.addEventListener('click',(e)=>{"
            "    e.preventDefault();"
            "    useEnhanced=!useEnhanced;"
            "    localStorage.setItem('ghostrollUseEnhanced',useEnhanced.toString());"
            "    updateEnhanceToggle();"
            "    if(lb&&lb.classList.contains('open')&&idx>=0){openAt(idx);}"
            "  });"
            "}"
            "if(!lb||!img||!cap||!sub||!counter||!loading) return;"
            "const tagsJsonCache=new Map();"
            "const tileTags=new Map();"
            "let tagsLoadStarted=false;"
            "function namesFromTagJson(j){"
            "  if(!j||typeof j!=='object') return [];"
            "  const labels=(j.labels&&Array.isArray(j.labels))?j.labels:[];"
            "  let names=labels.map(x=>x&&x.name).filter(Boolean).map(s=>String(s));"
            "  const faces=(j.faces&&Array.isArray(j.faces))?j.faces:[];"
            "  for(const f of faces){ if(f&&f.person) names.push(String(f.person)); }"
            "  return Array.from(new Set(names));"
            "}"
            "function setTagsLoading(){if(tags) tags.textContent='Tags: loading…';}"
            "function setTagsUnavailable(){if(tags) tags.textContent='Tags: unavailable';}"
            "function setTagsNone(){if(tags) tags.textContent='Tags: (none)';}"
            "function setTagsChips(names){"
            "  if(!tags) return;"
            "  tags.textContent='';"
            "  while(tags.firstChild) tags.removeChild(tags.firstChild);"
            "  if(!names||!names.length){setTagsNone();return;}"
            "  const label=document.createElement('span');"
            "  label.textContent='Tags:';"
            "  label.style.opacity='0.9';"
            "  tags.appendChild(label);"
            "  names.slice(0,12).forEach((name)=>{"
            "    const b=document.createElement('button');"
            "    b.type='button';"
            "    b.className='chip';"
            "    b.textContent=name;"
            "    b.addEventListener('click',(e)=>{"
            "      e.preventDefault();"
            "      if(filterInput){"
            "        filterInput.value=name;"
            "        filterInput.dispatchEvent(new Event('input',{bubbles:true}));"
            "        try{close();}catch(_){ }"
            "        setTimeout(()=>{try{filterInput.focus();}catch(_){ }},0);"
            "      }"
            "    });"
            "    tags.appendChild(b);"
            "  });"
            "}"
            "function getImageUrl(tile){"
            "  if(useEnhanced&&tile.dataset.enhanced){return tile.dataset.enhanced;}"
            "  return tile.dataset.full;"
            "}"
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
            "img.onload=function(){hideLoading();img.classList.remove('error');};"
            "img.onerror=function(){hideLoading();img.classList.add('error');img.alt='Failed to load image';};"
            "img.src=getImageUrl(t);"
            "img.alt=t.dataset.cap||'';"
            "cap.textContent=t.dataset.cap||'';"
            "sub.textContent=t.dataset.sub||'';"
            "if(tags){"
            "  tags.textContent='';"
            "  const tagsUrl=t.dataset.tags;"
            "  if(tagsUrl){"
            "    const cached=tagsJsonCache.get(tagsUrl);"
            "    if(cached&&cached.names){setTagsChips(cached.names);}"
            "    else{"
            "      setTagsLoading();"
            "      fetch(tagsUrl,{cache:'no-store'})"
            "        .then(r=>r.ok?r.json():null)"
            "        .then(j=>{"
            "          const names=namesFromTagJson(j||{});"
            "          tagsJsonCache.set(tagsUrl,{names});"
            "          if(idx>=0&&tiles[idx]===t){setTagsChips(names);}"
            "        })"
            "        .catch(()=>{ if(idx>=0&&tiles[idx]===t){setTagsUnavailable();} });"
            "    }"
            "  }"
            "}"
            "updateCounter();"
            "if(downloadBtn){downloadBtn.style.display='inline-flex';downloadBtn.href=getImageUrl(t);downloadBtn.download='';}"
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
            "tiles.forEach((t,idx) => {"
            "t.addEventListener('click',(e)=>{e.preventDefault();openAt(idx);});"
            "t.setAttribute('tabindex','0');"
            "t.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openAt(idx);}});"
            "});"
            "function setFilterStatus(txt){if(filterStatus) filterStatus.textContent=txt||'';}"
            "function parseTerms(q){return (q||'').toLowerCase().split(/\\s+/).map(s=>s.trim()).filter(Boolean);}"
            "function tileMatchesTerms(tile, terms){"
            "  if(!terms.length) return true;"
            "  const tagsArr=tileTags.get(tile);"
            "  if(!tagsArr) return false;"
            "  const hay=tagsArr.map(s=>String(s).toLowerCase()).join(' ');"
            "  return terms.every(t=>hay.includes(t));"
            "}"
            "function applyFilter(){"
            "  if(!filterInput) return;"
            "  const terms=parseTerms(filterInput.value);"
            "  if(!terms.length){"
            "    tiles.forEach(t=>{t.style.display='';});"
            "    setFilterStatus('');"
            "    updateTagChipActiveStates();"
            "    return;"
            "  }"
            "  let shown=0;"
            "  tiles.forEach(t=>{"
            "    const ok=tileMatchesTerms(t,terms);"
            "    t.style.display=ok?'':'none';"
            "    if(ok) shown++;"
            "  });"
            "  setFilterStatus('Showing '+shown+' / '+tiles.length);"
            "  updateTagChipActiveStates();"
            "}"
            "function updateTagChipActiveStates(){"
            "  if(!tagStripInner) return;"
            "  const terms=parseTerms(filterInput?filterInput.value:'');"
            "  const joined=terms.join(' ');"
            "  if(tagChipAll){"
            "    const allActive=!terms.length;"
            "    tagChipAll.classList.toggle('is-active',allActive);"
            "    tagChipAll.setAttribute('aria-pressed',allActive?'true':'false');"
            "  }"
            "  tagStripInner.querySelectorAll('button.filter-chip[data-tag-lower]').forEach((b)=>{"
            "    const low=b.dataset.tagLower||'';"
            "    const active=terms.length>0&&joined===low;"
            "    b.classList.toggle('is-active',active);"
            "    b.setAttribute('aria-pressed',active?'true':'false');"
            "  });"
            "}"
            "function rebuildTagChipsBar(){"
            "  if(!tagStripInner) return;"
            "  while(tagStripInner.firstChild) tagStripInner.removeChild(tagStripInner.firstChild);"
            "  const byLower=new Map();"
            "  tiles.forEach((tile)=>{"
            "    const arr=tileTags.get(tile);"
            "    if(!arr||!arr.length) return;"
            "    arr.forEach((name)=>{"
            "      const s=String(name);"
            "      const low=s.toLowerCase();"
            "      if(!byLower.has(low)) byLower.set(low,s);"
            "    });"
            "  });"
            "  const sorted=Array.from(byLower.entries()).sort((a,b)=>a[1].localeCompare(b[1],undefined,{sensitivity:'base'}));"
            "  sorted.forEach(([low,label])=>{"
            "    const b=document.createElement('button');"
            "    b.type='button';"
            "    b.className='btn filter-chip';"
            "    b.textContent=label;"
            "    b.dataset.tagLower=low;"
            "    b.setAttribute('aria-pressed','false');"
            "    b.addEventListener('click',(e)=>{"
            "      e.preventDefault();"
            "      if(filterInput){"
            "        filterInput.value=label;"
            "        filterInput.dispatchEvent(new Event('input',{bubbles:true}));"
            "      }"
            "    });"
            "    tagStripInner.appendChild(b);"
            "  });"
            "  updateTagChipActiveStates();"
            "}"
            "async function loadTagsForTile(tile){"
            "  if(tileTags.has(tile)) return;"
            "  const url=tile.dataset.tags;"
            "  if(!url){tileTags.set(tile,[]);return;}"
            "  try{"
            "    const r=await fetch(url,{cache:'no-store'});"
            "    if(!r.ok){tileTags.set(tile,[]);return;}"
            "    const j=await r.json();"
            "    const names=namesFromTagJson(j);"
            "    tileTags.set(tile,names);"
            "  }catch(e){tileTags.set(tile,[]);}"
            "}"
            "async function ensureAllTagsLoaded(){"
            "  if(tagsLoadStarted) return;"
            "  tagsLoadStarted=true;"
            "  const withUrls=tiles.filter(t=>t.dataset.tags);"
            "  if(!withUrls.length){setFilterStatus('');rebuildTagChipsBar();return;}"
            "  setFilterStatus('Loading tags…');"
            "  const concurrency=6;"
            "  let i=0;"
            "  const workers=new Array(concurrency).fill(0).map(async()=>{"
            "    while(i<withUrls.length){"
            "      const t=withUrls[i++];"
            "      await loadTagsForTile(t);"
            "      applyFilter();"
            "    }"
            "  });"
            "  await Promise.all(workers);"
            "  applyFilter();"
            "  rebuildTagChipsBar();"
            "}"
            "if(tagChipAll){"
            "  tagChipAll.addEventListener('click',(e)=>{"
            "    e.preventDefault();"
            "    if(filterInput){filterInput.value='';}"
            "    applyFilter();"
            "  });"
            "}"
            "if(filterInput){"
            "  filterInput.addEventListener('input',()=>{"
            "    const terms=parseTerms(filterInput.value);"
            "    if(terms.length){ensureAllTagsLoaded();}"
            "    applyFilter();"
            "  });"
            "  void ensureAllTagsLoaded();"
            "}"
            "if(closeBtn) closeBtn.addEventListener('click', close);"
            "if(nextBtn) nextBtn.addEventListener('click', next);"
            "if(prevBtn) prevBtn.addEventListener('click', prev);"
            "if(downloadBtn) downloadBtn.addEventListener('click',(e)=>{e.preventDefault();if(downloadBtn.href&&downloadBtn.href!='#'){window.open(downloadBtn.href,'_blank');}});"
            "lb.addEventListener('click',(e)=>{if(e.target===lb) close();});"
            "document.addEventListener('keydown',(e)=>{"
            "if(!lb.classList.contains('open')){"
            "  /* Keyboard shortcuts when lightbox is closed: arrow keys to navigate gallery */"
            "  if(e.key==='ArrowRight'||e.key==='ArrowLeft'){"
            "    e.preventDefault();"
            "    const currentIndex=document.activeElement instanceof Element&&tiles.includes(document.activeElement)?tiles.indexOf(document.activeElement):0;"
            "    const newIndex=(currentIndex+(e.key==='ArrowRight'?1:-1)+tiles.length)%tiles.length;"
            "    if(tiles[newIndex]){tiles[newIndex].focus();}"
            "  }"
            "  return;"
            "}"
            "if(e.key==='Escape'){e.preventDefault();close();}"
            "else if(e.key==='ArrowRight'||e.key==='ArrowDown'){e.preventDefault();next();}"
            "else if(e.key==='ArrowLeft'||e.key==='ArrowUp'){e.preventDefault();prev();}"
            "else if(e.key==='Home'){e.preventDefault();openAt(0);}"
            "else if(e.key==='End'){e.preventDefault();openAt(tiles.length-1);}"
            "else if((e.key==='d'||e.key==='D')&&e.target.tagName!=='INPUT'&&e.target.tagName!=='TEXTAREA'){"
            "  e.preventDefault();"
            "  if(downloadBtn&&downloadBtn.href&&downloadBtn.href!='#'){window.open(downloadBtn.href,'_blank');}"
            "}"
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

    items: list[tuple[str, str, str, str, None, None]] = []
    for t in thumbs:
        rel = t.relative_to(thumbs_dir)
        thumb_href = _posix(Path("thumbs") / rel)
        share_href = _posix(Path("share") / rel.with_suffix(".jpg"))
        title = rel.as_posix()
        items.append((thumb_href, share_href, title, "", None, None))

    _write_gallery_html(session_id=session_id, items=items, out_path=out_path, share_page_url=None)


def build_index_html_from_items(
    *,
    session_id: str,
    items: list[tuple],
    download_href: str | None,
    out_path: Path,
    share_page_url: str | None = None,
) -> None:
    _write_gallery_html(
        session_id=session_id,
        items=items,
        download_href=download_href,
        out_path=out_path,
        share_page_url=share_page_url,
    )


def build_index_html_presigned(
    *,
    session_id: str,
    items: list[tuple],
    download_href: str | None = None,
    out_path: Path,
    share_page_url: str | None = None,
) -> None:
    """
    items: list of (thumb_url, share_url, title, subtitle, enhanced_url, tags_url) — URLs should be fully-qualified.
    enhanced_url/tags_url can be None if enhanced version doesn't exist.
    share_page_url: presigned URL for this gallery page (index), shown as a copyable shortlink strip.
    """
    _write_gallery_html(
        session_id=session_id,
        items=items,
        download_href=download_href,
        out_path=out_path,
        share_page_url=share_page_url,
    )


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


