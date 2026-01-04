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
    # Try different possible import paths
    try:
        from waveshare_epd import epd2in13_V4  # type: ignore
        return epd2in13_V4.EPD()
    except ImportError:
        try:
            from waveshare_epd import epd2in13v4  # type: ignore
            return epd2in13v4.EPD()
        except ImportError:
            # Try direct import
            import epd2in13_V4  # type: ignore
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
        print("ghostroll-eink: initializing display...", file=sys.stderr)
        try:
            epd.init()
        except TypeError:
            try:
                epd.init(epd.FULL_UPDATE)  # type: ignore[attr-defined]
            except (TypeError, AttributeError):
                # Some versions don't need parameters
                epd.init()
        except Exception as e:
            print(f"ghostroll-eink: init error (continuing): {e}", file=sys.stderr)
        
        # Clear display (try different method names)
        try:
            epd.Clear(0xFF)
        except AttributeError:
            try:
                epd.clear(0xFF)  # lowercase
            except Exception:
                pass
        except Exception:
            pass

        print(f"ghostroll-eink: watching {status_png} (refresh: {refresh_seconds}s)", file=sys.stderr)
        last_mtime = 0.0

        while not STOP:
            try:
                st = status_png.stat()
                if st.st_mtime > last_mtime:
                    last_mtime = st.st_mtime
                    print(f"ghostroll-eink: updating display...", file=sys.stderr)
                    with Image.open(status_png) as im:
                        frame = _fit_for_epd(im, w=epd_w, h=epd_h)
                        # Try different display methods
                        try:
                            # Method 1: getbuffer then display (most common)
                            buf = epd.getbuffer(frame)
                            epd.display(buf)
                        except (AttributeError, TypeError):
                            try:
                                # Method 2: display image directly (some versions)
                                epd.display(frame)
                            except Exception as e:
                                print(f"ghostroll-eink: display method error: {e}", file=sys.stderr)
                                import traceback
                                traceback.print_exc(file=sys.stderr)
                                raise
                    print("ghostroll-eink: display updated", file=sys.stderr)
            except FileNotFoundError:
                pass
            except Exception as e:
                print(f"ghostroll-eink: render error: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
            time.sleep(refresh_seconds)

    finally:
        print("ghostroll-eink: shutting down...", file=sys.stderr)
        try:
            epd.sleep()
        except AttributeError:
            try:
                epd.Sleep()  # capitalized
            except Exception:
                pass
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


