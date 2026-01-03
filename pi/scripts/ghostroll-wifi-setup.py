#!/usr/bin/env python3

from __future__ import annotations

import html
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return default if v is None or v.strip() == "" else v


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)

def _run_best_effort(cmd: list[str]) -> None:
    try:
        _run(cmd, check=False)
    except Exception:
        pass


def _rfkill_unblock_best_effort() -> None:
    # If wifi is blocked, NM can't start AP mode. rfkill is common on Raspberry Pi OS.
    if Path("/usr/sbin/rfkill").exists() or Path("/usr/bin/rfkill").exists():
        _run_best_effort(["rfkill", "unblock", "all"])


def _nm_wifi_on_best_effort() -> None:
    _run_best_effort(["nmcli", "radio", "wifi", "on"])


def _nm_disconnect_wifi_best_effort(dev: str) -> None:
    # Ensure device is free to switch into AP mode.
    _run_best_effort(["nmcli", "dev", "disconnect", dev])


def _parse_size(s: str) -> tuple[int, int]:
    s = s.strip().lower()
    if "x" not in s:
        return (800, 480)
    w, h = s.split("x", 1)
    try:
        return (int(w), int(h))
    except Exception:
        return (800, 480)


def _write_status_best_effort(*, state: str, step: str, message: str) -> None:
    """
    Best-effort: if GhostRoll is installed system-wide (pi-gen image), reuse StatusWriter so the e-ink panel
    shows Wi-Fi setup instructions. On manual venv installs, this may not be importable; ignore failures.
    """
    try:
        from ghostroll.status import Status, StatusWriter, get_hostname, get_ip_address  # type: ignore

        json_path = Path(_env("GHOSTROLL_STATUS_PATH", "/home/pi/ghostroll/status.json"))
        img_path = Path(_env("GHOSTROLL_STATUS_IMAGE_PATH", "/home/pi/ghostroll/status.png"))
        img_size = _parse_size(_env("GHOSTROLL_STATUS_IMAGE_SIZE", "800x480"))

        sw = StatusWriter(json_path=json_path, image_path=img_path, image_size=img_size)
        sw.write(
            Status(
                state=state,
                step=step,
                message=message,
                hostname=get_hostname(),
                ip=get_ip_address(),
            )
        )
    except Exception:
        return


def _nm_connected() -> bool:
    try:
        # "connected", "connecting", "disconnected", ...
        out = _run(["nmcli", "-t", "-f", "STATE", "general"], check=True).stdout.strip()
        return out == "connected"
    except Exception:
        return False


def _nm_ready() -> bool:
    """Check if NetworkManager is running and ready."""
    try:
        # Check if NetworkManager service is active
        result = _run(["systemctl", "is-active", "NetworkManager"], check=False)
        if result.returncode != 0:
            return False
        # Check if nmcli can communicate with NetworkManager
        _run(["nmcli", "general", "status"], check=True)
        return True
    except Exception:
        return False


def _wifi_device() -> str | None:
    """
    Find a WiFi device using NetworkManager.
    Retries with delays to handle NetworkManager initialization timing.
    Also tries alternative detection methods as fallback.
    """
    max_retries = 10
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        # Wait for NetworkManager to be ready
        if not _nm_ready():
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                print("ghostroll-wifi-setup: NetworkManager not ready after retries", file=sys.stderr)
        
        try:
            # Primary method: use nmcli device list
            out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"], check=True).stdout
            for line in out.splitlines():
                parts = line.split(":")
                if len(parts) >= 3 and parts[1] == "wifi":
                    device = parts[0].strip()
                    if device:
                        return device
        except subprocess.CalledProcessError as e:
            # If nmcli fails, wait and retry
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                print(f"ghostroll-wifi-setup: nmcli device failed: {e}", file=sys.stderr)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                print(f"ghostroll-wifi-setup: error finding wifi device: {e}", file=sys.stderr)
    
    # Fallback: try using nmcli device status (different output format)
    try:
        out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"], check=False).stdout
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi":
                device = parts[0].strip()
                if device:
                    return device
    except Exception:
        pass
    
    # Fallback: try listing wifi devices directly
    try:
        out = _run(["nmcli", "-t", "-f", "DEVICE", "device", "wifi"], check=False).stdout
        for line in out.splitlines():
            device = line.strip()
            if device:
                return device
    except Exception:
        pass
    
    return None


def _scan_wifi(dev: str) -> list[tuple[str, str, str]]:
    """
    Returns (ssid, security, signal) rows.
    """
    try:
        out = _run(
            ["nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "dev", "wifi", "list", "ifname", dev],
            check=True,
        ).stdout
    except Exception:
        return []
    rows: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        ssid, sec, sig = (line.split(":", 2) + ["", "", ""])[:3]
        ssid = ssid.strip()
        if not ssid:
            continue
        rows.append((ssid, sec.strip(), sig.strip()))
    # Prefer stronger signal first
    def _sig_int(x: str) -> int:
        try:
            return int(x)
        except Exception:
            return -1

    rows.sort(key=lambda r: _sig_int(r[2]), reverse=True)
    return rows


def _ensure_hotspot(
    *,
    dev: str,
    con_name: str,
    ssid: str,
    password: str,
    ipv4_addr: str,
) -> None:
    """
    Creates/updates a hotspot connection and brings it up.
    Uses IPv4 shared mode so NM provides DHCP/NAT.
    """
    # Create or update connection
    existing = False
    try:
        _run(["nmcli", "-t", "-f", "NAME", "con", "show"], check=True)
        out = _run(["nmcli", "-t", "-f", "NAME", "con", "show"], check=True).stdout
        existing = any(line.strip() == con_name for line in out.splitlines())
    except Exception:
        existing = False

    if not existing:
        try:
            _run(
                [
                    "nmcli",
                    "dev",
                    "wifi",
                    "hotspot",
                    "ifname",
                    dev,
                    "con-name",
                    con_name,
                    "ssid",
                    ssid,
                    "password",
                    password,
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or str(e)).strip()
            raise RuntimeError(f"nmcli hotspot create failed: {msg}") from e

    # Ensure desired settings (idempotent)
    # Force deterministic gateway address (NM default is often 10.42.0.1)
    _run(["nmcli", "con", "mod", con_name, "ipv4.addresses", ipv4_addr], check=True)
    _run(["nmcli", "con", "mod", con_name, "ipv4.method", "shared"], check=True)
    _run(["nmcli", "con", "mod", con_name, "connection.autoconnect", "no"], check=True)
    _run(["nmcli", "con", "mod", con_name, "802-11-wireless.ssid", ssid], check=True)
    _run(["nmcli", "con", "mod", con_name, "802-11-wireless.mode", "ap"], check=True)
    _run(["nmcli", "con", "mod", con_name, "802-11-wireless-security.key-mgmt", "wpa-psk"], check=True)
    _run(["nmcli", "con", "mod", con_name, "802-11-wireless-security.psk", password], check=True)

    # Bring it up
    _run(["nmcli", "con", "up", con_name], check=True)


def _try_connect_client(dev: str, ssid: str, password: str | None) -> tuple[bool, str]:
    # Bring down hotspot if it's up; ignore errors.
    hotspot_con = _env("GHOSTROLL_WIFI_AP_CON_NAME", "ghostroll-setup")
    try:
        _run(["nmcli", "con", "down", hotspot_con], check=False)
    except Exception:
        pass

    cmd = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", dev]
    if password is not None and password != "":
        cmd += ["password", password]
    try:
        _run(cmd, check=True)
        return True, "connected"
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or e.stdout or str(e)).strip()
        return False, msg[-4000:] if msg else "connect failed"


class _Handler(BaseHTTPRequestHandler):
    server_version = "ghostroll-wifi-setup/1.0"

    def _page(self, *, title: str, body_html: str, status: int = 200) -> None:
        page = f"""<!doctype html>
<html><head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; }}
    .card {{ max-width: 760px; margin: 0 auto; padding: 18px; border: 1px solid #ddd; border-radius: 10px; }}
    h1 {{ margin-top: 0; font-size: 20px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 8px; border-bottom: 1px solid #eee; }}
    input, button {{ font-size: 16px; padding: 10px; }}
    input {{ width: 100%; box-sizing: border-box; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    @media (max-width: 640px) {{ .row {{ grid-template-columns: 1fr; }} }}
    .muted {{ color: #666; font-size: 13px; }}
  </style>
</head><body>
  <div class="card">
    {body_html}
    <p class="muted">GhostRoll Wi‑Fi setup (AP fallback). If you don’t see your network, refresh.</p>
  </div>
</body></html>"""
        data = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/scan"}:
            self._page(title="Not found", body_html="<h1>Not found</h1>", status=404)
            return

        dev = self.server.dev  # type: ignore[attr-defined]
        rows = _scan_wifi(dev) if dev else []
        table_rows = "\n".join(
            f"<tr><td>{html.escape(ssid)}</td><td>{html.escape(sec)}</td><td>{html.escape(sig)}</td></tr>"
            for ssid, sec, sig in rows[:30]
        )
        body = f"""
<h1>Configure Wi‑Fi</h1>
<p>Pick an SSID and enter the password. The Pi will switch off the setup hotspot and join your network.</p>
<form method="POST" action="/connect">
  <div class="row">
    <div>
      <label>SSID</label><br>
      <input name="ssid" placeholder="Network name" required>
    </div>
    <div>
      <label>Password</label><br>
      <input name="password" placeholder="Wi‑Fi password" type="password">
    </div>
  </div>
  <p><button type="submit">Connect</button></p>
</form>

<h2>Nearby networks</h2>
<table>
  <thead><tr><th>SSID</th><th>Security</th><th>Signal</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>
"""
        self._page(title="GhostRoll Wi‑Fi Setup", body_html=body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/connect":
            self._page(title="Not found", body_html="<h1>Not found</h1>", status=404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        ssid = (form.get("ssid") or [""])[0].strip()
        password = (form.get("password") or [""])[0]
        dev = self.server.dev  # type: ignore[attr-defined]
        ok, msg = _try_connect_client(dev, ssid, password)
        if ok:
            body = f"<h1>Connected</h1><p>Joined <b>{html.escape(ssid)}</b>. You can now SSH to the Pi on your LAN.</p>"
            self._page(title="Connected", body_html=body)
            # Stop the server shortly after responding
            self.server.stop_after = time.time() + 1.5  # type: ignore[attr-defined]
            return
        body = f"<h1>Failed</h1><p>Could not connect to <b>{html.escape(ssid)}</b>.</p><pre>{html.escape(msg)}</pre><p><a href=\"/\">Try again</a></p>"
        self._page(title="Failed", body_html=body, status=500)

    def log_message(self, fmt: str, *args) -> None:
        # Keep systemd logs clean; print minimal.
        sys.stderr.write(f"ghostroll-wifi-setup: {self.address_string()} - {fmt % args}\n")


def main() -> int:
    enable = _env("GHOSTROLL_WIFI_AP_FALLBACK", "1")
    if enable not in {"1", "true", "yes", "on"}:
        return 0

    wait_seconds = int(_env("GHOSTROLL_WIFI_CONNECT_TIMEOUT_SECONDS", "30"))
    ap_ssid = _env("GHOSTROLL_WIFI_AP_SSID", "ghostroll-setup")
    ap_pass = _env("GHOSTROLL_WIFI_AP_PASSWORD", "ghostroll-setup")
    ap_con = _env("GHOSTROLL_WIFI_AP_CON_NAME", "ghostroll-setup")
    ap_ipv4 = _env("GHOSTROLL_WIFI_AP_IPV4", "192.168.4.1/24")
    listen_host = _env("GHOSTROLL_WIFI_PORTAL_HOST", "0.0.0.0")
    listen_port = int(_env("GHOSTROLL_WIFI_PORTAL_PORT", "8080"))

    # Ensure Wi-Fi isn't blocked/disabled BEFORE trying to detect device.
    # This is critical for hub mode or when WiFi is initially disabled.
    _rfkill_unblock_best_effort()
    _nm_wifi_on_best_effort()
    
    # Wait a bit for NetworkManager to initialize and WiFi to become available
    # (especially important on boot or in hub mode)
    time.sleep(2.0)
    
    dev = _wifi_device()
    if dev is None:
        print("ghostroll-wifi-setup: no wifi device found (nmcli)", file=sys.stderr)
        # Provide diagnostic information
        try:
            nm_status = _run(["systemctl", "status", "NetworkManager", "--no-pager", "-l"], check=False)
            print(f"ghostroll-wifi-setup: NetworkManager service status (exit {nm_status.returncode}):", file=sys.stderr)
            if nm_status.stdout:
                print(nm_status.stdout[:500], file=sys.stderr)
            
            # Check for WiFi hardware
            try:
                radio_out = _run(["nmcli", "-t", "-f", "WIFI,WIFI-HW", "radio"], check=False).stdout.strip()
                print(f"ghostroll-wifi-setup: WiFi radio status: {radio_out}", file=sys.stderr)
            except Exception:
                pass
            
            # List all devices
            try:
                all_devs = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"], check=False).stdout.strip()
                print(f"ghostroll-wifi-setup: All NetworkManager devices:\n{all_devs}", file=sys.stderr)
            except Exception:
                pass
        except Exception:
            pass
        return 2

    # Wait for normal connection
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if _nm_connected():
            return 0
        time.sleep(1.0)

    # Start hotspot
    try:
        _nm_disconnect_wifi_best_effort(dev)
        _ensure_hotspot(dev=dev, con_name=ap_con, ssid=ap_ssid, password=ap_pass, ipv4_addr=ap_ipv4)
    except Exception as e:
        # Provide actionable debug hints.
        print(f"ghostroll-wifi-setup: failed to start hotspot: {e}", file=sys.stderr)
        try:
            state = _run(["nmcli", "-t", "-f", "STATE", "general"], check=False).stdout.strip()
            radios = _run(["nmcli", "-t", "-f", "WIFI,WIFI-HW", "radio"], check=False).stdout.strip()
            devs = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"], check=False).stdout.strip()
            print(f"ghostroll-wifi-setup: nmcli general STATE={state}", file=sys.stderr)
            print(f"ghostroll-wifi-setup: nmcli radio {radios}", file=sys.stderr)
            print(f"ghostroll-wifi-setup: nmcli devices:\n{devs}", file=sys.stderr)
        except Exception:
            pass
        return 2

    # Serve portal
    server = HTTPServer((listen_host, listen_port), _Handler)
    server.dev = dev  # type: ignore[attr-defined]
    server.stop_after = None  # type: ignore[attr-defined]
    ap_ip = ap_ipv4.split("/")[0]
    portal_url = f"http://{ap_ip}:{listen_port}"
    print(f"ghostroll-wifi-setup: AP '{ap_ssid}' up; portal on {portal_url}")
    _write_status_best_effort(
        state="idle",
        step="wifi",
        message=f"Wi‑Fi setup: join '{ap_ssid}' then open {portal_url}",
    )
    try:
        while True:
            server.handle_request()
            stop_after = getattr(server, "stop_after", None)
            if stop_after is not None and time.time() >= stop_after:
                break
    finally:
        server.server_close()
        _write_status_best_effort(state="idle", step="wifi", message="Wi‑Fi setup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


