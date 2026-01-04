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
    # Provided by Waveshare's Python lib
    # Try different possible import paths depending on installation method
    import sys
    from pathlib import Path
    
    errors = []
    
    # Method 1: waveshare-epd pip package (standard structure)
    try:
        from waveshare_epd import epd2in13_V4  # type: ignore
        return epd2in13_V4.EPD()
    except ImportError as e:
        errors.append(f"waveshare_epd.epd2in13_V4: {e}")
    
    # Method 2: waveshare-epd with lowercase v
    try:
        from waveshare_epd import epd2in13v4  # type: ignore
        return epd2in13v4.EPD()
    except ImportError as e:
        errors.append(f"waveshare_epd.epd2in13v4: {e}")
    
    # Method 3: Direct import (if installed from GitHub repo)
    try:
        import epd2in13_V4  # type: ignore
        return epd2in13_V4.EPD()
    except ImportError as e:
        errors.append(f"epd2in13_V4: {e}")
    
    # Method 4: From waveshare_epd subdirectory structure
    try:
        from waveshare_epd.epd2in13_V4 import EPD  # type: ignore
        return EPD()
    except ImportError as e:
        errors.append(f"waveshare_epd.epd2in13_V4.EPD: {e}")
    
    # Method 5: Try alternative package name
    try:
        import waveshare_epd.epd2in13v4 as epd_module  # type: ignore
        return epd_module.EPD()
    except ImportError as e:
        errors.append(f"waveshare_epd.epd2in13v4 (alt): {e}")
    
    # Method 6: From local lib directory (if repo cloned)
    lib_paths = [
        Path("/usr/local/src/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        Path("/home/pi/e-Paper/RaspberryPi_JetsonNano/python/lib"),
        Path(__file__).parent.parent.parent / "lib",
    ]
    for lib_path in lib_paths:
        if lib_path.exists():
            sys.path.insert(0, str(lib_path))
            try:
                import epd2in13_V4  # type: ignore
                return epd2in13_V4.EPD()
            except ImportError:
                continue
    
    # If all methods fail, raise a helpful error with diagnostics
    error_msg = "Could not import epd2in13_V4 module.\n\n"
    error_msg += "Tried import paths:\n"
    for err in errors[:3]:  # Show first 3 errors
        error_msg += f"  - {err}\n"
    error_msg += "\nTo fix, try one of these:\n"
    error_msg += "  1. Install via pip: pip3 install waveshare-epd\n"
    error_msg += "  2. Or clone the repo and copy lib files:\n"
    error_msg += "     git clone https://github.com/waveshareteam/e-Paper.git\n"
    error_msg += "     cp -r e-Paper/RaspberryPi_JetsonNano/python/lib/* /usr/local/lib/python3.*/site-packages/\n"
    error_msg += "  3. Or install system packages:\n"
    error_msg += "     sudo apt-get install python3-rpi.gpio python3-spidev\n"
    
    raise ImportError(error_msg)


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


