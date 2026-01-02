from __future__ import annotations

import json
import os
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
    - Fallback: UDP socket trick (doesn't send packets)
    """
    # Linux / Raspberry Pi OS
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
        # Render a simple monochrome status image for e-ink displays.
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return

        w, h = self.image_size
        img = Image.new("1", (w, h), 1)  # 1-bit, white background
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        # Try to use a larger font for headers/titles if available
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except Exception:
            title_font = font

        lines: list[tuple[str, object]] = []  # (text, font) - font is ImageFont object
        
        state = payload.get("state", "").upper()
        step = payload.get("step", "")
        message = payload.get("message", "")
        counts = payload.get("counts") or {}
        
        # Header: GhostRoll with state
        header = f"GhostRoll — {state}" if state else "GhostRoll"
        lines.append((header, title_font))
        
        # Most important: Status message (prominent)
        if message:
            # Special handling for completion - check if message contains "Remove" hint
            if state == "DONE" and step == "done" and "Remove" in message:
                lines.append(("✅ Complete", title_font))
                lines.append(("Remove SD card now", font))
            elif state == "DONE" and step == "done":
                lines.append(("✅ Complete", title_font))
            elif state == "ERROR":
                lines.append((f"❌ ERROR: {message}", title_font))
            else:
                # Show the message prominently
                lines.append((message, font))
        
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
                    lines.append((f"{label}: {done}/{total} ({pct}%)", font))
                    break
            
            # Show key counts for running operations
            key_counts = []
            if "discovered" in counts:
                key_counts.append(f"Found: {counts['discovered']}")
            if "new" in counts:
                key_counts.append(f"New: {counts['new']}")
            if "processed" in counts:
                key_counts.append(f"Done: {counts['processed']}")
            if key_counts:
                lines.append((" ".join(key_counts), font))
        
        # Session info (when available)
        if payload.get("session_id"):
            session_id = payload["session_id"]
            # Truncate long session IDs for display
            if len(session_id) > 20:
                session_id = session_id[:17] + "..."
            lines.append((f"Session: {session_id}", font))
        
        # SSH info (only when idle/waiting, not cluttering during operations)
        if state in ("IDLE", "") and (payload.get("hostname") or payload.get("ip")):
            hn = payload.get("hostname") or "unknown"
            ip = payload.get("ip") or "no IP yet"
            lines.append((f"SSH: pi@{ip}", font))
            if hn != "unknown":
                lines.append((f"({hn})", font))
        
        # URL ready (when complete)
        if payload.get("url"):
            lines.append(("Share URL ready", font))
            lines.append(("(see share.txt/QR)", font))
        
        # Render lines with appropriate spacing
        y = 10
        line_height = 16
        for line_text, line_font in lines:
            # Truncate lines that are too long for display
            max_width = w - 24
            # Simple truncation - in practice PIL will handle overflow
            draw.text((12, y), line_text, font=line_font, fill=0)
            y += line_height
            # Don't overflow the image
            if y > h - line_height:
                break

        assert self.image_path is not None
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure temp file still ends with .png so PIL knows the format.
        tmp = self.image_path.with_suffix(".tmp.png")
        img.save(tmp, format="PNG")
        tmp.replace(self.image_path)


