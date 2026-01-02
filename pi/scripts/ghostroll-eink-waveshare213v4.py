#!/usr/bin/env python3

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from PIL import Image, ImageOps


STOP = False


def _on_signal(_sig, _frame):
    global STOP
    STOP = True


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _load_epd():
    # Provided by Waveshare's Python lib (usually module `waveshare_epd`)
    from waveshare_epd import epd2in13_V4  # type: ignore

    return epd2in13_V4.EPD()


def _fit_for_epd(img: Image.Image, *, w: int, h: int) -> Image.Image:
    # Ensure monochrome, correct aspect, and orientation.
    # Many users mount the HAT in landscape; we keep the 250x122 native resolution.
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    img = ImageOps.fit(img, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    # Convert to 1-bit (black/white)
    return img.convert("1")


def main() -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if not _env_bool("GHOSTROLL_EINK_ENABLE", False):
        # Exit cleanly when not enabled.
        return 0

    status_png = Path(os.environ.get("GHOSTROLL_STATUS_IMAGE_PATH", "/home/pi/ghostroll/status.png"))
    refresh_seconds = float(os.environ.get("GHOSTROLL_EINK_REFRESH_SECONDS", "5"))

    # Waveshare 2.13" V4 (B/W) is 250x122
    epd_w = int(os.environ.get("GHOSTROLL_EINK_WIDTH", "250"))
    epd_h = int(os.environ.get("GHOSTROLL_EINK_HEIGHT", "122"))

    try:
        epd = _load_epd()
    except Exception as e:
        print(f"ghostroll-eink: failed to import Waveshare EPD driver: {e}", file=sys.stderr)
        return 2

    try:
        # Init and clear
        try:
            epd.init()
        except TypeError:
            epd.init(epd.FULL_UPDATE)  # type: ignore[attr-defined]
        try:
            epd.Clear(0xFF)
        except Exception:
            pass

        last_mtime = 0.0

        while not STOP:
            try:
                st = status_png.stat()
                if st.st_mtime > last_mtime:
                    last_mtime = st.st_mtime
                    with Image.open(status_png) as im:
                        frame = _fit_for_epd(im, w=epd_w, h=epd_h)
                        buf = epd.getbuffer(frame)
                        epd.display(buf)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"ghostroll-eink: render error: {e}", file=sys.stderr)
            time.sleep(refresh_seconds)

    finally:
        try:
            epd.sleep()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


