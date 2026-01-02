from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_ip_address() -> str | None:
    """
    Best-effort "what IP should I SSH to?" helper.
    - On Linux, prefer `hostname -I` (common on Raspberry Pi OS)
    - On macOS, use `ifconfig` or fallback to UDP socket trick
    - Fallback: UDP socket trick (doesn't send packets)
    """
    system = platform.system().lower()
    
    # Linux / Raspberry Pi OS
    if system == "linux":
        try:
            res = subprocess.run(["hostname", "-I"], capture_output=True, text=True)
            if res.returncode == 0:
                ips = [p.strip() for p in res.stdout.strip().split() if p.strip()]
                # Skip loopback and link-local if possible
                for ip in ips:
                    if ip.startswith("127.") or ip.startswith("169.254."):
                        continue
                    return ip
                if ips:
                    return ips[0]
        except Exception:
            pass
    
    # macOS - use ifconfig to get IP
    if system == "darwin":
        try:
            res = subprocess.run(
                ["ifconfig"], capture_output=True, text=True, timeout=2
            )
            if res.returncode == 0:
                # Parse ifconfig output for inet addresses
                for line in res.stdout.splitlines():
                    if "inet " in line and "127.0.0.1" not in line:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == "inet" and i + 1 < len(parts):
                                ip = parts[i + 1]
                                # Skip loopback and link-local
                                if not ip.startswith("127.") and not ip.startswith("169.254."):
                                    return ip
        except Exception:
            pass

    # Generic fallback
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        finally:
            s.close()
    except Exception:
        pass

    return None


@dataclass
class Status:
    state: str  # idle|running|error|done
    step: str
    message: str
    session_id: str | None = None
    volume: str | None = None
    counts: dict[str, int] | None = None
    url: str | None = None
    qr_path: str | None = None  # Path to QR code PNG file
    hostname: str | None = None
    ip: str | None = None
    updated_unix: float | None = None


class StatusWriter:
    def __init__(
        self,
        *,
        json_path: Path,
        image_path: Path | None = None,
        image_size: tuple[int, int] = (800, 480),
    ) -> None:
        self.json_path = json_path
        self.image_path = image_path
        self.image_size = image_size

    def write(self, status: Status) -> None:
        status.updated_unix = time.time()
        payload = {
            "state": status.state,
            "step": status.step,
            "message": status.message,
            "session_id": status.session_id,
            "volume": status.volume,
            "counts": status.counts or {},
            "url": status.url,
            "qr_path": status.qr_path,
            "hostname": status.hostname,
            "ip": status.ip,
            "updated_unix": status.updated_unix,
        }
        self._atomic_write_json(self.json_path, payload)
        if self.image_path is not None:
            self._write_status_image(payload)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + os.linesep, encoding="utf-8")
        tmp.replace(path)

    def _write_status_image(self, payload: dict) -> None:
        # Render a clean, user-friendly monochrome status image for e-ink displays.
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return

        w, h = self.image_size
        img = Image.new("1", (w, h), 1)  # 1-bit, white background
        draw = ImageDraw.Draw(img)
        
        # Load fonts - try platform-specific paths first, then fallback
        default_font = None
        title_font = None
        small_font = None
        system = platform.system().lower()
        
        # Try platform-specific font paths
        font_paths = []
        if system == "darwin":
            # macOS font paths
            font_paths = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ]
        elif system == "linux":
            # Linux font paths
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
        
        # Try to load fonts from platform-specific paths
        for font_path in font_paths:
            try:
                if Path(font_path).exists():
                    default_font = ImageFont.truetype(font_path, 12)
                    # Try to find bold variant
                    bold_path = font_path.replace("Regular", "Bold").replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                    if Path(bold_path).exists():
                        title_font = ImageFont.truetype(bold_path, 16)
                    else:
                        title_font = ImageFont.truetype(font_path, 16)
                    small_font = ImageFont.truetype(font_path, 10)
                    break
            except Exception:
                continue
        
        # Fallback to default fonts if platform-specific fonts failed
        if default_font is None:
            try:
                default_font = ImageFont.load_default()
                title_font = default_font
                small_font = default_font
            except Exception:
                # Last resort: use built-in default
                default_font = ImageFont.load_default()
                title_font = default_font
                small_font = default_font

        state = payload.get("state", "").upper()
        step = payload.get("step", "")
        message = payload.get("message", "")
        counts = payload.get("counts") or {}
        qr_path_str = payload.get("qr_path")
        
        # Try to load QR code if available
        qr_img = None
        if qr_path_str:
            try:
                qr_path = Path(qr_path_str)
                if qr_path.exists():
                    qr_img = Image.open(qr_path).convert("1")
            except Exception:
                pass
        
        # Determine layout based on display size
        is_small_display = w < 400  # e-ink displays like 250x122
        
        if is_small_display:
            # Compact layout for small e-ink displays (e.g., 250x122)
            # QR code on right, text on left
            text_x = 8
            text_y = 8
            line_height = 14
            
            # Header
            header = f"GhostRoll" if not state else f"GhostRoll — {state}"
            draw.text((text_x, text_y), header, font=title_font, fill=0)
            text_y += line_height + 2
            
            # Status message
            if message:
                if state == "DONE" and step == "done":
                    draw.text((text_x, text_y), "✓ Complete", font=title_font, fill=0)
                    text_y += line_height
                    if "Remove" in message:
                        draw.text((text_x, text_y), "Remove SD", font=default_font, fill=0)
                        text_y += line_height
                elif state == "ERROR":
                    draw.text((text_x, text_y), f"✗ {message[:20]}", font=title_font, fill=0)
                    text_y += line_height
                else:
                    # Truncate long messages
                    msg = message[:25] + "..." if len(message) > 25 else message
                    draw.text((text_x, text_y), msg, font=default_font, fill=0)
                    text_y += line_height
            
            # Progress (when running)
            if state == "RUNNING":
                step_lower = step.lower()
                if "process" in step_lower and "processed_done" in counts and "processed_total" in counts:
                    done = int(counts.get("processed_done", 0))
                    total = int(counts.get("processed_total", 0))
                    if total > 0:
                        pct = int((done / total) * 100)
                        draw.text((text_x, text_y), f"Processing: {done}/{total} ({pct}%)", font=small_font, fill=0)
                        text_y += line_height - 2
                elif "upload" in step_lower and "uploaded_done" in counts and "uploaded_total" in counts:
                    done = int(counts.get("uploaded_done", 0))
                    total = int(counts.get("uploaded_total", 0))
                    if total > 0:
                        pct = int((done / total) * 100)
                        draw.text((text_x, text_y), f"Uploading: {done}/{total} ({pct}%)", font=small_font, fill=0)
                        text_y += line_height - 2
            
            # QR code on the right side (if available)
            if qr_img:
                # Calculate available space: leave room for text on left (text_x + some margin)
                text_area_width = 120  # Reserve space for text content
                available_width = w - text_area_width - 8
                available_height = h - text_y - 20  # Leave room for label below QR
                qr_size = min(80, available_width, available_height)
                if qr_size > 0:
                    qr_resized = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
                    qr_x = w - qr_size - 8
                    qr_y = text_y
                    img.paste(qr_resized, (qr_x, qr_y))
                    # Label below QR
                    draw.text((qr_x, qr_y + qr_size + 2), "Scan QR", font=small_font, fill=0)
            
            # SSH info (only when idle)
            if state in ("IDLE", "") and payload.get("ip"):
                ip = payload.get("ip", "")
                draw.text((text_x, h - line_height - 4), f"SSH: pi@{ip}", font=small_font, fill=0)
        
        else:
            # Larger display layout (e.g., 800x480)
            # QR code prominently displayed, status info around it
            padding = 16
            text_x = padding
            text_y = padding
            line_height = 18
            
            # Header at top
            header = f"GhostRoll" if not state else f"GhostRoll — {state}"
            draw.text((text_x, text_y), header, font=title_font, fill=0)
            text_y += line_height + 4
            
            # Status message
            if message:
                if state == "DONE" and step == "done":
                    draw.text((text_x, text_y), "✓ Complete", font=title_font, fill=0)
                    text_y += line_height
                    if "Remove" in message:
                        draw.text((text_x, text_y), "Remove SD card now", font=default_font, fill=0)
                        text_y += line_height
                elif state == "ERROR":
                    draw.text((text_x, text_y), f"✗ ERROR: {message}", font=title_font, fill=0)
                    text_y += line_height
                else:
                    draw.text((text_x, text_y), message, font=default_font, fill=0)
                    text_y += line_height
            
            # Progress information (when running)
            if state == "RUNNING":
                step_lower = step.lower()
                prog_pairs = [
                    ("process", "processed_done", "processed_total", "Processing"),
                    ("upload", "uploaded_done", "uploaded_total", "Uploading"),
                    ("presign", "presigned_done", "presigned_total", "Generating link"),
                ]
                for step_name, done_k, total_k, label in prog_pairs:
                    if step_name in step_lower and total_k in counts and done_k in counts and counts[total_k] > 0:
                        done = int(counts[done_k])
                        total = int(counts[total_k])
                        pct = int((done / total) * 100)
                        draw.text((text_x, text_y), f"{label}: {done}/{total} ({pct}%)", font=default_font, fill=0)
                        text_y += line_height
                        break
                
                # Key counts
                key_counts = []
                if "discovered" in counts:
                    key_counts.append(f"Found: {counts['discovered']}")
                if "new" in counts:
                    key_counts.append(f"New: {counts['new']}")
                if "processed" in counts:
                    key_counts.append(f"Done: {counts['processed']}")
                if key_counts:
                    draw.text((text_x, text_y), "  ".join(key_counts), font=default_font, fill=0)
                    text_y += line_height
            
            # QR code - prominently displayed
            if qr_img:
                # Position QR code: right side for larger displays
                qr_size = min(200, h - text_y - padding - 40, w - text_x - padding - 20)
                qr_resized = qr_img.resize((qr_size, qr_size), Image.Resampling.LANCZOS)
                qr_x = w - qr_size - padding
                qr_y = padding
                img.paste(qr_resized, (qr_x, qr_y))
                
                # Label above QR
                label_text = "Scan to view gallery"
                # Measure text width to center it
                bbox = draw.textbbox((0, 0), label_text, font=default_font)
                label_width = bbox[2] - bbox[0]
                label_x = qr_x + (qr_size - label_width) // 2
                draw.text((label_x, qr_y - line_height - 4), label_text, font=default_font, fill=0)
            
            # Session info
            if payload.get("session_id"):
                session_id = payload["session_id"]
                if len(session_id) > 30:
                    session_id = session_id[:27] + "..."
                draw.text((text_x, text_y), f"Session: {session_id}", font=small_font, fill=0)
                text_y += line_height - 4
            
            # SSH info (only when idle)
            if state in ("IDLE", "") and (payload.get("hostname") or payload.get("ip")):
                hn = payload.get("hostname") or "unknown"
                ip = payload.get("ip") or "no IP yet"
                draw.text((text_x, h - line_height - padding), f"SSH: pi@{ip}", font=default_font, fill=0)
                if hn != "unknown":
                    draw.text((text_x, h - padding), f"({hn})", font=small_font, fill=0)

        assert self.image_path is not None
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure temp file still ends with .png so PIL knows the format.
        tmp = self.image_path.with_suffix(".tmp.png")
        img.save(tmp, format="PNG")
        tmp.replace(self.image_path)


