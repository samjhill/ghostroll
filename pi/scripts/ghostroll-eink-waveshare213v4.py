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
    
    # If already 1-bit, we need to be careful with resizing to preserve text
    if img.mode == "1":
        # For 1-bit images, resize using nearest neighbor first to preserve sharp edges,
        # then optionally apply smoothing. But for text, we want sharp edges.
        # Convert to grayscale first for better resampling, then back to 1-bit
        img_gray = img.convert("L")
        # Use LANCZOS for better quality when downscaling text
        img_resized = ImageOps.fit(img_gray, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        # Convert back to 1-bit with threshold to preserve text
        # Use a threshold that keeps text visible (text is typically black/0 in 1-bit)
        threshold = 128
        return img_resized.point(lambda p: 0 if p < threshold else 255, mode="1")
    
    # Convert to grayscale first
    img = img.convert("L")
    
    # Enhance contrast - use a more aggressive approach for text visibility
    # First, try to enhance contrast
    img = ImageOps.autocontrast(img, cutoff=2)  # More aggressive contrast
    
    # Resize to target dimensions
    img = ImageOps.fit(img, (w, h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    
    # Convert to 1-bit with threshold to ensure text is visible
    # Use a threshold that preserves text (typically text is darker)
    # Threshold of 128 means anything darker than 50% gray becomes black
    threshold = 128
    img = img.point(lambda p: 0 if p < threshold else 255, mode="1")
    
    return img


def _check_spi_setup() -> None:
    """Check if SPI is enabled and accessible."""
    import subprocess
    from pathlib import Path
    
    errors = []
    
    # Check if SPI is enabled in config
    config_paths = [
        Path("/boot/firmware/config.txt"),
        Path("/boot/config.txt"),
    ]
    spi_enabled = False
    for config_path in config_paths:
        if config_path.exists():
            try:
                config_content = config_path.read_text()
                if "dtparam=spi=on" in config_content or "dtoverlay=spi" in config_content:
                    spi_enabled = True
                    break
            except Exception:
                pass
    
    if not spi_enabled:
        errors.append("SPI is not enabled in /boot/config.txt (add: dtparam=spi=on)")
    
    # Check if SPI device files exist
    spi_devices = [
        Path("/dev/spidev0.0"),
        Path("/dev/spidev0.1"),
    ]
    spi_devices_exist = any(dev.exists() for dev in spi_devices)
    if not spi_devices_exist:
        errors.append("SPI device files not found (/dev/spidev0.0 or /dev/spidev0.1)")
    
    # Check if user has permission (or running as root)
    if os.geteuid() != 0:
        # Check if user is in spi group
        try:
            import grp
            import pwd
            current_user = pwd.getpwuid(os.getuid()).pw_name
            try:
                spi_group = grp.getgrnam("spi")
                if current_user not in spi_group.gr_mem:
                    errors.append(f"User '{current_user}' not in 'spi' group (run: sudo usermod -a -G spi {current_user}, then logout/login)")
            except KeyError:
                # spi group doesn't exist
                errors.append("'spi' group not found (SPI may not be properly configured)")
        except ImportError:
            # grp/pwd not available (unlikely on Linux, but handle gracefully)
            pass
        except Exception:
            pass
    
    if errors:
        error_msg = "SPI setup issues detected:\n"
        for err in errors:
            error_msg += f"  - {err}\n"
        error_msg += "\nTo fix:\n"
        error_msg += "  1. Enable SPI: sudo raspi-config -> Interface Options -> SPI -> Enable\n"
        error_msg += "  2. Or edit /boot/config.txt and add: dtparam=spi=on\n"
        error_msg += "  3. Reboot after enabling SPI\n"
        error_msg += "  4. If not running as root, add user to spi group: sudo usermod -a -G spi $USER\n"
        print(f"ghostroll-eink: {error_msg}", file=sys.stderr)
        # Don't exit - let it try and fail with a clearer error


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

    # Check SPI setup before trying to load the driver
    _check_spi_setup()

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
        except OSError as e:
            if e.errno == 9:  # Bad file descriptor
                print("ghostroll-eink: SPI communication error (errno 9: bad file descriptor)", file=sys.stderr)
                print("ghostroll-eink: This usually means SPI is not enabled or accessible.", file=sys.stderr)
                print("ghostroll-eink: Enable SPI: sudo raspi-config -> Interface Options -> SPI -> Enable", file=sys.stderr)
                print("ghostroll-eink: Then reboot: sudo reboot", file=sys.stderr)
                return 3
            raise
        except Exception as e:
            print(f"ghostroll-eink: init error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Don't continue if init fails
            return 3
        
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
                        # Log original image info for debugging
                        print(f"ghostroll-eink: source image: {im.size}, mode: {im.mode}", file=sys.stderr)
                        
                        # Check source image pixel distribution
                        if im.mode == "1":
                            src_pixels = list(im.getdata())
                            src_black = sum(1 for p in src_pixels if p == 0)
                            src_total = len(src_pixels)
                            src_black_pct = (src_black / src_total * 100) if src_total > 0 else 0
                            print(f"ghostroll-eink: source has {src_black} black pixels ({src_black_pct:.1f}%)", file=sys.stderr)
                            if src_black == 0:
                                print("ghostroll-eink: WARNING: source image is all white! GhostRoll may not be generating status correctly.", file=sys.stderr)
                        
                        frame = _fit_for_epd(im, w=epd_w, h=epd_h)
                        
                        # Log processed image info
                        print(f"ghostroll-eink: processed image: {frame.size}, mode: {frame.mode}", file=sys.stderr)
                        
                        # Quick check: count black vs white pixels (for diagnostics)
                        if frame.mode == "1":
                            pixels = list(frame.getdata())
                            # In mode "1", 0 = black, 1 = white (or 255 = white depending on implementation)
                            black_count = sum(1 for p in pixels if p == 0)
                            white_count = sum(1 for p in pixels if p != 0)
                            total = len(pixels)
                            black_pct = (black_count / total * 100) if total > 0 else 0
                            print(f"ghostroll-eink: pixel stats: {black_count} black ({black_pct:.1f}%), {white_count} white (of {total} total)", file=sys.stderr)
                            if black_count == 0:
                                print("ghostroll-eink: WARNING: processed image is all white! Text may have been lost during resize.", file=sys.stderr)
                            elif black_count < total * 0.01:  # Less than 1% black
                                print(f"ghostroll-eink: WARNING: very few black pixels ({black_pct:.1f}%), text may not be visible", file=sys.stderr)
                            elif black_pct > 50:
                                print(f"ghostroll-eink: NOTE: image is mostly black ({black_pct:.1f}%), may need inversion", file=sys.stderr)
                        
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


