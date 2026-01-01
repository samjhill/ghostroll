from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Status:
    state: str  # idle|running|error|done
    step: str
    message: str
    session_id: str | None = None
    volume: str | None = None
    counts: dict[str, int] | None = None
    url: str | None = None
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


