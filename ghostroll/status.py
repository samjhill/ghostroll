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


def get_pisugar_battery() -> dict[str, int | bool] | None:
    """
    Get battery status from PiSugar via the PiSugar Power Manager API.
    
    Tries multiple methods in order:
    1. Unix socket API (piSugar-server.sock)
    2. HTTP API (port 8421) with authentication
    3. Alternative methods (sysfs, etc.)
    
    Returns a dict with:
    - percentage: int (0-100)
    - is_charging: bool
    - voltage: int (millivolts, optional)
    
    Returns None if PiSugar is not available or if there's an error.
    """
    # Method 1: Try Unix socket API first (fastest and most common)
    pisugar_socket = Path("/tmp/pisugar-server.sock")
    if pisugar_socket.exists():
        try:
            # Try using Python socket first (more portable)
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect(str(pisugar_socket))
                sock.sendall(b"get battery\n")
                
                # Read response - PiSugar returns just a number like "95"
                response_bytes = b""
                while True:
                    chunk = sock.recv(1024)
                    if not chunk:
                        break
                    response_bytes += chunk
                    # Stop if we have a reasonable amount of data
                    if len(response_bytes) > 512:
                        break
                
                sock.close()
                response = response_bytes.decode("utf-8", errors="ignore").strip()
                
                # PiSugar socket API returns just a number (0-100) for "get battery"
                # Try to parse as integer first
                try:
                    percentage = int(float(response))
                    if 0 <= percentage <= 100:
                        # Get charging status separately
                        is_charging = False
                        try:
                            sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                            sock2.settimeout(1.0)
                            sock2.connect(str(pisugar_socket))
                            sock2.sendall(b"get battery_charging\n")
                            charge_response = b""
                            while True:
                                chunk = sock2.recv(256)
                                if not chunk:
                                    break
                                charge_response += chunk
                                if len(charge_response) > 128:
                                    break
                            sock2.close()
                            charge_str = charge_response.decode("utf-8", errors="ignore").strip().lower()
                            # PiSugar returns "true" or "false" for charging status
                            is_charging = charge_str in ("true", "1", "yes")
                        except Exception:
                            pass  # If we can't get charging status, just use False
                        
                        return {
                            "percentage": percentage,
                            "is_charging": is_charging,
                            "voltage": None,
                        }
                except (ValueError, TypeError):
                    pass  # Not a plain number, try other parsing methods
                
                # Try parsing as JSON (in case response format changed)
                if response:
                    try:
                        data = json.loads(response)
                        percentage = data.get("percentage") or data.get("battery") or data.get("level")
                        is_charging = data.get("charging") or data.get("is_charging") or False
                        voltage = data.get("voltage") or data.get("voltage_mv")
                        
                        if percentage is not None:
                            return {
                                "percentage": int(percentage),
                                "is_charging": bool(is_charging),
                                "voltage": int(voltage) if voltage is not None else None,
                            }
                    except (json.JSONDecodeError, ValueError, TypeError):
                        # Try parsing key-value format
                        # Example: "battery: 85\ncharging: false"
                        percentage = None
                        is_charging = False
                        voltage = None
                        
                        for line in response.splitlines():
                            if ":" in line:
                                key, value = line.split(":", 1)
                                key = key.strip().lower()
                                value = value.strip()
                                
                                if "battery" in key or "percentage" in key or "level" in key:
                                    try:
                                        percentage = int(float(value))
                                    except (ValueError, TypeError):
                                        pass
                                elif "charging" in key:
                                    is_charging = value.lower() in ("true", "1", "yes", "on")
                                elif "voltage" in key:
                                    try:
                                        voltage = int(float(value))
                                    except (ValueError, TypeError):
                                        pass
                        
                        if percentage is not None:
                            return {
                                "percentage": percentage,
                                "is_charging": is_charging,
                                "voltage": voltage,
                            }
            except (OSError, socket.error, Exception):
                # Socket failed, try netcat fallback
                try:
                    result = subprocess.run(
                        ["nc", "-U", "/tmp/pisugar-server.sock"],
                        input="get battery\n",
                        capture_output=True,
                        text=True,
                        timeout=2,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        response = result.stdout.strip()
                        try:
                            percentage = int(float(response))
                            if 0 <= percentage <= 100:
                                # Try to get charging status
                                is_charging = False
                                try:
                                    charge_result = subprocess.run(
                                        ["nc", "-U", "/tmp/pisugar-server.sock"],
                                        input="get battery_charging\n",
                                        capture_output=True,
                                        text=True,
                                        timeout=1,
                                    )
                                    if charge_result.returncode == 0:
                                        charge_str = charge_result.stdout.strip().lower()
                                        is_charging = charge_str in ("true", "1", "yes")
                                except Exception:
                                    pass
                                
                                return {
                                    "percentage": percentage,
                                    "is_charging": is_charging,
                                    "voltage": None,
                                }
                        except (ValueError, TypeError):
                            pass
                except (subprocess.TimeoutExpired, FileNotFoundError, OSError, Exception):
                    pass
        except Exception:
            pass
    
    # Method 2: Try HTTP API (port 8421) if socket failed
    # First try to get authentication token
    try:
        # Try default username/password (often empty or "pi")
        for username, password in [("pi", ""), ("", ""), ("admin", "admin")]:
            try:
                import urllib.request
                import urllib.parse
                
                login_url = f"http://127.0.0.1:8421/login?username={urllib.parse.quote(username)}&password={urllib.parse.quote(password)}"
                req = urllib.request.Request(login_url, method="POST")
                with urllib.request.urlopen(req, timeout=2) as response:
                    token = response.read().decode("utf-8").strip()
                    if token:
                        # Got token, now execute get battery command
                        exec_url = f"http://127.0.0.1:8421/exec?token={urllib.parse.quote(token)}"
                        exec_data = "get battery".encode("utf-8")
                        exec_req = urllib.request.Request(
                            exec_url,
                            data=exec_data,
                            headers={"Content-Type": "text/plain"},
                            method="POST",
                        )
                        with urllib.request.urlopen(exec_req, timeout=2) as exec_response:
                            response_text = exec_response.read().decode("utf-8").strip()
                            try:
                                percentage = int(float(response_text))
                                if 0 <= percentage <= 100:
                                    # Try to get charging status
                                    is_charging = False
                                    try:
                                        charge_data = "get battery_charging".encode("utf-8")
                                        charge_req = urllib.request.Request(
                                            exec_url,
                                            data=charge_data,
                                            headers={"Content-Type": "text/plain"},
                                            method="POST",
                                        )
                                        with urllib.request.urlopen(charge_req, timeout=2) as charge_response:
                                            charge_text = charge_response.read().decode("utf-8").strip().lower()
                                            is_charging = charge_text in ("true", "1", "yes")
                                    except Exception:
                                        pass
                                    
                                    return {
                                        "percentage": percentage,
                                        "is_charging": is_charging,
                                        "voltage": None,
                                    }
                            except (ValueError, TypeError):
                                pass
                        break  # Successfully tried HTTP API, don't try other credentials
            except Exception:
                continue
    except Exception:
        pass
    
    # Method 3: Try alternative methods (sysfs, etc.)
    # Check for sysfs battery interface
    try:
        # PiSugar might expose battery info via sysfs
        sysfs_paths = [
            Path("/sys/class/power_supply/pisugar/battery_percentage"),
            Path("/sys/class/power_supply/pisugar/capacity"),
            Path("/sys/class/power_supply/battery/capacity"),
        ]
        for sysfs_path in sysfs_paths:
            if sysfs_path.exists():
                try:
                    percentage_str = sysfs_path.read_text(encoding="utf-8").strip()
                    percentage = int(float(percentage_str))
                    if 0 <= percentage <= 100:
                        # Try to get charging status
                        is_charging = False
                        status_path = sysfs_path.parent / "status"
                        if status_path.exists():
                            try:
                                status = status_path.read_text(encoding="utf-8").strip().lower()
                                is_charging = status == "charging"
                            except Exception:
                                pass
                        
                        return {
                            "percentage": percentage,
                            "is_charging": is_charging,
                            "voltage": None,
                        }
                except Exception:
                    continue
    except Exception:
        pass
    
    # All methods failed
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
    battery_percentage: int | None = None  # 0-100
    battery_charging: bool | None = None


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
        
        # Try to get battery status if not already set
        if status.battery_percentage is None:
            battery_info = get_pisugar_battery()
            if battery_info:
                status.battery_percentage = battery_info.get("percentage")
                status.battery_charging = battery_info.get("is_charging")
        
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
            "battery_percentage": status.battery_percentage,
            "battery_charging": status.battery_charging,
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
        # Use larger, more readable fonts for e-ink displays
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
            # Linux font paths - prioritize bold fonts for better readability
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
        
        # Try to load fonts from platform-specific paths with larger sizes for readability
        for font_path in font_paths:
            try:
                if Path(font_path).exists():
                    # Use larger fonts for better e-ink readability
                    default_font = ImageFont.truetype(font_path, 13)  # Increased from 12
                    # Try to find bold variant for title
                    bold_path = font_path.replace("Regular", "Bold").replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
                    if "Bold" in font_path or Path(bold_path).exists():
                        if "Bold" in font_path:
                            title_font_path = font_path
                        else:
                            title_font_path = bold_path
                        title_font = ImageFont.truetype(title_font_path, 18)  # Increased from 16 for better visibility
                    else:
                        title_font = ImageFont.truetype(font_path, 18)
                    small_font = ImageFont.truetype(font_path, 11)  # Increased from 10
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
        battery_percentage = payload.get("battery_percentage")
        battery_charging = payload.get("battery_charging", False)
        
        # Helper function to draw battery indicator
        def _draw_battery_indicator(x: int, y: int, percentage: int | None, charging: bool, size: int = 20) -> None:
            """Draw a battery icon with percentage and charging indicator."""
            if percentage is None:
                return
            
            # Battery outline: rectangle with a small tab on the right
            # Make it more visible with thicker lines
            battery_w = size
            battery_h = int(size * 0.65)  # Slightly taller for better visibility
            tab_w = 3  # Wider tab
            tab_h = int(size * 0.35)
            outline_width = 2  # Thicker outline for e-ink visibility
            
            # Draw battery body with thicker outline
            draw.rectangle([x, y, x + battery_w, y + battery_h], outline=0, width=outline_width)
            # Draw battery tab (right side) - make it more visible
            tab_x = x + battery_w
            tab_y = y + (battery_h - tab_h) // 2
            draw.rectangle([tab_x, tab_y, tab_x + tab_w, tab_y + tab_h], fill=0, outline=0)
            
            # Draw battery fill based on percentage
            if percentage > 0:
                # Account for thicker outline
                padding = outline_width
                fill_w = max(1, int((battery_w - (padding * 2)) * (percentage / 100)))
                fill_x = x + padding
                fill_y = y + padding
                fill_h = battery_h - (padding * 2)
                
                # Color coding: red < 20%, normal otherwise
                # For monochrome, we'll use different fill patterns
                if percentage < 20:
                    # Low battery: use diagonal lines pattern for visibility
                    for i in range(0, fill_w, 3):
                        draw.line([fill_x + i, fill_y, fill_x + i, fill_y + fill_h], fill=0, width=1)
                else:
                    # Normal: solid fill
                    draw.rectangle([fill_x, fill_y, fill_x + fill_w, fill_y + fill_h], fill=0)
            
            # Draw charging indicator (lightning bolt) if charging
            if charging:
                # More visible lightning bolt in center
                bolt_x = x + battery_w // 2
                bolt_y = y + battery_h // 2
                # Draw inverted lightning (white on black fill) for visibility
                if percentage > 0:
                    # White lightning on black fill
                    draw.line([bolt_x - 2, bolt_y - 3, bolt_x, bolt_y], fill=1, width=2)
                    draw.line([bolt_x, bolt_y, bolt_x + 2, bolt_y + 3], fill=1, width=2)
                else:
                    # Black lightning on white background
                    draw.line([bolt_x - 2, bolt_y - 3, bolt_x, bolt_y], fill=0, width=2)
                    draw.line([bolt_x, bolt_y, bolt_x + 2, bolt_y + 3], fill=0, width=2)
            
            # Draw percentage text next to battery (small font)
            pct_text = f"{percentage}%"
            text_x = x + battery_w + tab_w + 4  # More spacing
            text_y = y + (battery_h // 2) - 4  # Better vertical centering
            draw.text((text_x, text_y), pct_text, font=small_font, fill=0)
        
        # Try to load QR code if available
        # CRITICAL: QR code must be loaded for DONE state - ensure it's always attempted
        qr_img = None
        if qr_path_str:
            try:
                qr_path = Path(qr_path_str)
                # Try to load the QR code - this is especially important in DONE state
                if qr_path.exists():
                    # Verify file is readable and has content
                    try:
                        file_size = qr_path.stat().st_size
                        if file_size > 0:
                            qr_img = Image.open(qr_path).convert("1")
                            # Verify image was loaded successfully
                            qr_img.load()  # Force load to catch any errors
                            # Log success for debugging (especially in DONE state)
                            import sys
                            print(f"ghostroll-status: QR code loaded successfully from {qr_path} ({file_size} bytes)", file=sys.stderr)
                        else:
                            # File exists but is empty - log for debugging
                            import sys
                            print(f"ghostroll-status: QR code file {qr_path} exists but is empty ({file_size} bytes)", file=sys.stderr)
                    except OSError as e:
                        # File might have been deleted or is inaccessible
                        import sys
                        print(f"ghostroll-status: Cannot access QR code file {qr_path}: {e}", file=sys.stderr)
                else:
                    # File doesn't exist - log for debugging (critical in DONE state)
                    import sys
                    print(f"ghostroll-status: QR code file {qr_path} does not exist (state: {state})", file=sys.stderr)
            except Exception as e:
                # Log the error so we can debug why QR code isn't loading
                import sys
                print(f"ghostroll-status: Failed to load QR code from {qr_path_str} (state: {state}): {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
        else:
            # No QR path provided - log this especially in DONE state
            if state == "DONE":
                import sys
                print(f"ghostroll-status: WARNING: No QR code path provided in DONE state", file=sys.stderr)
        
        # Determine layout based on display size
        is_small_display = w < 400  # e-ink displays like 250x122
        
        if is_small_display:
            # Compact layout for small e-ink displays (e.g., 250x122)
            # Optimized for 250x122: maximize QR code size for phone scanning
            # Improved spacing and readability
            text_x = 6
            text_y = 28  # Start text at fixed position for consistent layout
            line_height = 15  # Increased from 13 for better readability
            small_line_height = 12  # Increased from 11
            
            # Initialize text_area_width early to avoid UnboundLocalError
            # Default to full width if no QR code, otherwise set by QR code layout
            text_area_width = w - 12  # Default: full width minus margins
            
            # Helper to format user-friendly messages
            def _format_message(msg: str, state: str) -> str:
                """Make messages more concise and user-friendly."""
                # Remove trailing ellipsis if present
                msg = msg.rstrip("…").rstrip(".")
                
                # Map technical messages to user-friendly ones
                replacements = {
                    "Scanning DCIM for media": "Scanning card",
                    "No new files detected": "No new photos",
                    "Copying originals": "Copying photos",
                    "Generating share images + thumbnails": "Processing images",
                    "Uploading photos to S3": "Uploading",
                    "Uploading to S3": "Uploading",
                    "Generating share link": "Creating link",
                    "Complete. Remove SD card when ready": "Done! Remove card",
                    "Complete. Remove SD card now": "Done! Remove card",
                    "Waiting for SD card": "Insert SD card",
                }
                for old, new in replacements.items():
                    if old in msg:
                        msg = msg.replace(old, new)
                        break
                
                # Truncate if still too long
                if len(msg) > 22:
                    msg = msg[:19] + "..."
                return msg
            
            # Battery indicator in top-right corner (before QR code area)
            # Position it above QR code area when QR is present, or top-right if no QR
            if battery_percentage is not None:
                battery_size = 22  # Slightly smaller to give more space to QR code
                # Estimate text width (percentage can be 1-3 digits + %)
                text_width = 20 if battery_percentage < 100 else 25
                total_width = battery_size + 3 + 4 + text_width  # battery + tab + spacing + text
                # Position battery at top-right, but leave space for QR code on right side
                battery_x = w - total_width - 6
                battery_y = 4  # Top margin
                _draw_battery_indicator(battery_x, battery_y, battery_percentage, battery_charging, size=battery_size)
            
            # Header - bold and clear
            if state == "IDLE":
                header = "GhostRoll"
            elif state == "RUNNING":
                header = "GhostRoll"
            elif state == "DONE":
                header = "✓ Done"
            elif state == "ERROR":
                header = "✗ Error"
            else:
                header = "GhostRoll"
            
            # Draw header with better spacing
            draw.text((text_x, text_y), header, font=title_font, fill=0)
            text_y += line_height + 2  # Increased spacing for better readability
            
            # Status message - user-friendly formatting with better spacing
            if message:
                friendly_msg = _format_message(message, state)
                if state == "DONE":
                    # Done state: clear, bold message
                    draw.text((text_x, text_y), friendly_msg, font=default_font, fill=0)
                    text_y += line_height + 1  # Extra spacing after main message
                    # Show session info if available (only if space allows)
                    if payload.get("session_id") and text_y + small_line_height < h - 16:
                        session_short = payload["session_id"][:18] + "..." if len(payload.get("session_id", "")) > 18 else payload["session_id"]
                        draw.text((text_x, text_y), f"S: {session_short}", font=small_font, fill=0)
                        text_y += small_line_height
                elif state == "ERROR":
                    # Error state: show first line of error clearly
                    error_lines = friendly_msg.split("\n")
                    draw.text((text_x, text_y), error_lines[0][:22], font=default_font, fill=0)
                    text_y += line_height
                else:
                    # Normal state: clear message
                    draw.text((text_x, text_y), friendly_msg, font=default_font, fill=0)
                    text_y += line_height
            
            # Progress and file counts (when running) - improved formatting
            if state == "RUNNING":
                step_lower = step.lower()
                
                # Show file counts if available (more concise)
                if "new" in counts:
                    new_count = int(counts.get("new", 0))
                    if new_count > 0:
                        draw.text((text_x, text_y), f"{new_count} new", font=small_font, fill=0)
                        text_y += small_line_height
                elif "discovered" in counts:
                    disc_count = int(counts.get("discovered", 0))
                    if disc_count > 0:
                        draw.text((text_x, text_y), f"{disc_count} found", font=small_font, fill=0)
                        text_y += small_line_height
                
                # Processing progress (more compact)
                if "process" in step_lower and "processed_done" in counts and "processed_total" in counts:
                    done = int(counts.get("processed_done", 0))
                    total = int(counts.get("processed_total", 0))
                    if total > 0:
                        pct = int((done / total) * 100)
                        draw.text((text_x, text_y), f"Proc: {done}/{total} ({pct}%)", font=small_font, fill=0)
                        text_y += small_line_height
                
                # Upload progress (more compact)
                if "upload" in step_lower and "uploaded_done" in counts and "uploaded_total" in counts:
                    done = int(counts.get("uploaded_done", 0))
                    total = int(counts.get("uploaded_total", 0))
                    if total > 0:
                        pct = int((done / total) * 100)
                        draw.text((text_x, text_y), f"Up: {done}/{total} ({pct}%)", font=small_font, fill=0)
                        text_y += small_line_height
                
                # RAW upload progress
                if step_lower == "raw_upload":
                    if "raw_files_compressing" in counts and "raw_files_total" in counts:
                        compressing = int(counts.get("raw_files_compressing", 0))
                        total = int(counts.get("raw_files_total", 0))
                        if total > 0:
                            pct = int((compressing / total) * 100)
                            draw.text((text_x, text_y), f"RAW: {compressing}/{total} ({pct}%)", font=small_font, fill=0)
                            text_y += small_line_height
                    elif "raw_uploaded" in counts and counts.get("raw_uploaded", 0) > 0:
                        draw.text((text_x, text_y), "RAW: Uploaded", font=small_font, fill=0)
                        text_y += small_line_height
                
                # Show volume name if available (only if space allows)
                if payload.get("volume") and text_y + small_line_height < h - 16:
                    vol_name = Path(payload["volume"]).name
                    if len(vol_name) > 14:
                        vol_name = vol_name[:11] + "..."
                    draw.text((text_x, text_y), f"Card: {vol_name}", font=small_font, fill=0)
                    text_y += small_line_height
            
            # QR code on the right side (if available)
            # Show QR code whenever it's available, including in DONE state
            # Priority: Maximize QR code size for reliable phone scanning
            if qr_img:
                # Maximize QR code size: use most of the right side of display
                # Reserve space for text on left (reduced to minimum)
                text_area_width = 100  # Reduced to maximize QR code space
                qr_margin = 3  # Minimal margin around QR
                available_width = w - text_area_width - qr_margin
                
                # Position QR code starting below battery indicator (if present)
                # Start QR code at y=30 to leave room for battery at top
                qr_start_y = 32 if battery_percentage is not None else 6
                
                # Calculate available height - leave room for label at bottom
                label_height = 14
                bottom_info_height = small_line_height + 4 if state in ("IDLE", "DONE", "") and payload.get("ip") else 0
                available_height = h - qr_start_y - label_height - bottom_info_height - 2
                
                # Make QR code as large as possible for reliable phone scanning
                # Target: minimum 90px, prefer 100px+ for easy scanning
                qr_size = min(available_width, available_height)
                # Ensure QR is at least 85px for reliable phone scanning (QR codes need good size)
                if qr_size >= 85:
                    # Add white border (quiet zone) around QR code for better scanning
                    # This helps phones detect QR code boundaries more easily
                    border_pixels = 3  # 3-pixel white border around QR code
                    qr_with_border_size = qr_size + (border_pixels * 2)
                    
                    # Create a temporary image with white border
                    qr_with_border = Image.new("1", (qr_with_border_size, qr_with_border_size), 1)  # 1 = white
                    
                    # Resize QR code with sharp edges (NEAREST for 1-bit to preserve sharpness)
                    if qr_img.mode == "1":
                        # For 1-bit images, use nearest neighbor to preserve sharp QR code edges
                        # This is critical for QR code scanning - blurry edges make scanning fail
                        qr_resized = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                    else:
                        # Convert to 1-bit first, then resize
                        qr_1bit = qr_img.convert("1")
                        qr_resized = qr_1bit.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                    
                    # Paste QR code into center of white border image
                    qr_with_border.paste(qr_resized, (border_pixels, border_pixels))
                    
                    # Position QR code on right side with margin
                    qr_x = w - qr_with_border_size - qr_margin
                    qr_y = qr_start_y
                    
                    # Paste QR code with border onto main image
                    img.paste(qr_with_border, (qr_x, qr_y))
                    
                    # Label below QR code - centered and clear
                    label_text = "Scan"
                    # Measure text to center it
                    bbox = draw.textbbox((0, 0), label_text, font=small_font)
                    label_width = bbox[2] - bbox[0]
                    label_x = qr_x + (qr_with_border_size - label_width) // 2
                    label_y = qr_y + qr_with_border_size + 2
                    draw.text((label_x, label_y), label_text, font=small_font, fill=0)
                else:
                    # QR code too small - log warning but still try to display
                    import sys
                    print(f"ghostroll-status: WARNING: QR code size {qr_size}px may be too small for reliable scanning (minimum recommended: 85px)", file=sys.stderr)
                    # Still try to display it
                    if qr_img.mode == "1":
                        qr_resized = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                    else:
                        qr_1bit = qr_img.convert("1")
                        qr_resized = qr_1bit.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                    qr_x = w - qr_size - qr_margin
                    qr_y = qr_start_y
                    img.paste(qr_resized, (qr_x, qr_y))
            elif qr_path_str:
                # QR path was provided but image failed to load - log for debugging
                import sys
                print(f"ghostroll-status: QR code path provided ({qr_path_str}) but image not loaded - check logs above", file=sys.stderr)
            
            # Bottom info bar - improved spacing and readability
            bottom_y = h - small_line_height - 3
            bottom_info_parts = []
            
            # SSH info (when idle or done) - only show if QR code is not present or we have space
            if state in ("IDLE", "DONE", "") and payload.get("ip"):
                ip = payload.get("ip", "")
                # Shorten IP if needed for small display
                if len(ip) > 14:
                    ip = ip[:11] + "..."
                bottom_info_parts.append(f"SSH: {ip}")
            
            # Session ID when done (if no IP or space available) - very concise
            if state == "DONE" and payload.get("session_id") and not payload.get("ip"):
                session_short = payload["session_id"][:12] + "..." if len(payload.get("session_id", "")) > 12 else payload["session_id"]
                bottom_info_parts.append(session_short)
            
            # Show bottom info only if we have room (don't overlap with QR code)
            if bottom_info_parts:
                bottom_text = " | ".join(bottom_info_parts)
                # Limit width to fit on screen without overlapping QR code
                max_text_width = text_area_width - 4
                # Rough estimate: 6 pixels per character for small font
                max_chars = max_text_width // 6
                if len(bottom_text) > max_chars:
                    bottom_text = bottom_text[:max_chars - 3] + "..."
                draw.text((text_x, bottom_y), bottom_text, font=small_font, fill=0)
        
        else:
            # Larger display layout (e.g., 800x480)
            # QR code prominently displayed, status info around it
            padding = 16
            text_x = padding
            text_y = padding
            line_height = 18
            
            # Battery indicator in top-right corner
            if battery_percentage is not None:
                battery_size = 28  # Larger for better visibility
                # Estimate text width
                text_width = 25 if battery_percentage < 100 else 30
                total_width = battery_size + 3 + 4 + text_width
                battery_x = w - total_width - padding
                battery_y = padding
                _draw_battery_indicator(battery_x, battery_y, battery_percentage, battery_charging, size=battery_size)
            
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
                    ("raw_upload", "raw_files_compressing", "raw_files_total", "RAW Files"),
                ]
                for step_name, done_k, total_k, label in prog_pairs:
                    if step_name == "raw_upload" and step_lower == "raw_upload":
                        # Special handling for RAW upload: show compression or upload status
                        if "raw_files_compressing" in counts and "raw_files_total" in counts and counts["raw_files_total"] > 0:
                            compressing = int(counts.get("raw_files_compressing", 0))
                            total = int(counts.get("raw_files_total", 0))
                            pct = int((compressing / total) * 100)
                            draw.text((text_x, text_y), f"RAW: {compressing}/{total} ({pct}%)", font=default_font, fill=0)
                            text_y += line_height
                            break
                        elif "raw_uploaded" in counts and counts.get("raw_uploaded", 0) > 0:
                            draw.text((text_x, text_y), "RAW Files: Uploaded", font=default_font, fill=0)
                            text_y += line_height
                            break
                    elif step_name in step_lower and total_k in counts and done_k in counts and counts[total_k] > 0:
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
            
            # QR code - prominently displayed with white border for better scanning
            # Always shown when available, including in DONE state
            if qr_img:
                # Position QR code: right side for larger displays
                # Make QR code larger for better phone scanning (prefer 250px+ for large displays)
                max_qr_size = min(350, h - padding * 2, w - text_x - padding - 40)
                qr_size = max(200, max_qr_size)  # Ensure at least 200px for large displays (better for scanning)
                
                # Add white border (quiet zone) around QR code for better scanning
                border_pixels = 6  # Larger border for big displays
                qr_with_border_size = qr_size + (border_pixels * 2)
                
                # Create a temporary image with white border
                qr_with_border = Image.new("1", (qr_with_border_size, qr_with_border_size), 1)  # 1 = white
                
                # Resize QR code with sharp edges (NEAREST for 1-bit to preserve sharpness)
                if qr_img.mode == "1":
                    qr_resized = qr_img.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                else:
                    qr_1bit = qr_img.convert("1")
                    qr_resized = qr_1bit.resize((qr_size, qr_size), Image.Resampling.NEAREST)
                
                # Paste QR code into center of white border image
                qr_with_border.paste(qr_resized, (border_pixels, border_pixels))
                
                qr_x = w - qr_with_border_size - padding
                qr_y = padding
                img.paste(qr_with_border, (qr_x, qr_y))
                
                # Label above QR
                label_text = "Scan to view gallery"
                # Measure text width to center it
                bbox = draw.textbbox((0, 0), label_text, font=default_font)
                label_width = bbox[2] - bbox[0]
                label_x = qr_x + (qr_with_border_size - label_width) // 2
                draw.text((label_x, qr_y - line_height - 4), label_text, font=default_font, fill=0)
            elif qr_path_str:
                # QR path was provided but image failed to load - log for debugging
                import sys
                print(f"ghostroll-status: QR code path provided ({qr_path_str}) but image not loaded - check logs above", file=sys.stderr)
            
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
        # Sync the temp file to disk before atomic replace
        # This ensures the e-ink display script picks up changes immediately
        try:
            fd = os.open(str(tmp), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            # If sync fails, continue anyway - file should still be written
            pass
        tmp.replace(self.image_path)
        # Also sync the final file to ensure it's visible to the e-ink watcher
        try:
            fd = os.open(str(self.image_path), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            # If sync fails, continue anyway
            pass


