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

        lines: list[str] = []
        lines.append(f"GhostRoll — {payload.get('state', '')}".strip())
        if payload.get("hostname") or payload.get("ip"):
            hn = payload.get("hostname") or "unknown"
            ip = payload.get("ip") or "no IP yet"
            lines.append(f"SSH: pi@{ip}  ({hn})")
        if payload.get("session_id"):
            lines.append(f"Session: {payload['session_id']}")
        if payload.get("step"):
            lines.append(f"Step: {payload['step']}")
        if payload.get("message"):
            lines.append(payload["message"])

        counts = payload.get("counts") or {}
        if counts:
            # Keep stable ordering for readability
            keys = ["discovered", "new", "skipped", "processed", "uploaded"]
            parts = []
            for k in keys:
                if k in counts:
                    parts.append(f"{k}:{counts[k]}")
            extra = [f"{k}:{v}" for k, v in counts.items() if k not in keys]
            parts.extend(extra)
            if parts:
                lines.append(" ".join(parts))

        if payload.get("url"):
            lines.append("Share URL ready (see share.txt / QR)")

        y = 12
        for line in lines:
            draw.text((12, y), line, font=font, fill=0)
            y += 16

        assert self.image_path is not None
        self.image_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure temp file still ends with .png so PIL knows the format.
        tmp = self.image_path.with_suffix(".tmp.png")
        img.save(tmp, format="PNG")
        tmp.replace(self.image_path)


