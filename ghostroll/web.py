"""
Lightweight web interface for GhostRoll.

Serves existing files (status.json, status.png, session galleries) with minimal overhead.
Designed to have virtually no performance impact on the main pipeline.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class GhostRollWebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for GhostRoll web interface."""
    
    def __init__(self, *args, status_path: Path, sessions_dir: Path, **kwargs):
        self.status_path = status_path
        self.sessions_dir = sessions_dir
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        """Override to reduce logging verbosity (only log errors)."""
        # Only log if it's an error (4xx/5xx)
        if args and len(args) > 0:
            status_code = args[1] if len(args) > 1 else None
            if status_code and isinstance(status_code, int) and status_code >= 400:
                super().log_message(format, *args)
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        
        try:
            if path == "/" or path == "/index.html":
                self._serve_index()
            elif path == "/status.json":
                self._serve_status_json()
            elif path == "/status.png":
                self._serve_status_png()
            elif path == "/sessions":
                self._serve_sessions_list()
            elif path.startswith("/sessions/"):
                session_path = path[len("/sessions/"):]
                if "/" in session_path:
                    # Path within a session (e.g., /sessions/session-id/index.html)
                    parts = session_path.split("/", 1)
                    session_id = parts[0]
                    file_path = parts[1] if len(parts) > 1 else "index.html"
                    self._serve_session_file(session_id, file_path)
                else:
                    # Just /sessions/session-id - redirect to index.html
                    session_id = session_path
                    self._redirect_to_session(session_id)
            else:
                self._send_error(404, "Not found")
        except Exception as e:
            self._send_error(500, f"Internal error: {e}")
    
    def _serve_index(self):
        """Serve the main index page with status and session links."""
        status_data = self._read_status_json()
        
        # Build HTML
        html = """<!DOCTYPE html>
<html>
<head>
    <title>GhostRoll</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }
        h1 { color: #333; }
        .status { background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 20px 0; }
        .status.running { background: #fff4e1; }
        .status.done { background: #e8f5e9; }
        .status.error { background: #ffebee; }
        .sessions { margin-top: 30px; }
        .session { padding: 10px; border: 1px solid #ddd; border-radius: 4px; margin: 10px 0; }
        .session a { text-decoration: none; color: #1976d2; }
        .qr-preview { max-width: 200px; margin: 10px 0; }
        pre { background: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }
    </style>
</head>
<body>
    <h1>GhostRoll</h1>
"""
        
        if status_data:
            state = status_data.get("state", "unknown")
            html += f'    <div class="status {state}">\n'
            html += f'        <h2>Status: {state.upper()}</h2>\n'
            html += f'        <p><strong>{status_data.get("message", "")}</strong></p>\n'
            
            if status_data.get("session_id"):
                html += f'        <p>Session: <code>{status_data["session_id"]}</code></p>\n'
            
            if status_data.get("url"):
                html += f'        <p><a href="{status_data["url"]}" target="_blank">View Gallery →</a></p>\n'
            
            if status_data.get("counts"):
                counts = status_data["counts"]
                html += "        <ul>\n"
                for key, value in counts.items():
                    html += f"            <li>{key}: {value}</li>\n"
                html += "        </ul>\n"
            
            html += "    </div>\n"
        else:
            html += '    <div class="status">\n'
            html += "        <p>Status file not found</p>\n"
            html += "    </div>\n"
        
        # List sessions
        sessions = self._list_sessions()
        if sessions:
            html += '    <div class="sessions">\n'
            html += "        <h2>Sessions</h2>\n"
            for session_id in sessions:
                html += f'        <div class="session">\n'
                html += f'            <a href="/sessions/{session_id}">{session_id}</a>\n'
                html += "        </div>\n"
            html += "    </div>\n"
        
        html += """    <hr>
    <p><small>
        <a href="/status.json">Status JSON</a> |
        <a href="/status.png">Status Image</a> |
        <a href="/sessions">All Sessions</a>
    </small></p>
</body>
</html>"""
        
        self._send_html(html)
    
    def _serve_status_json(self):
        """Serve status.json directly."""
        if not self.status_path.exists():
            self._send_error(404, "Status file not found")
            return
        
        try:
            content = self.status_path.read_text(encoding="utf-8")
            self._send_json(content)
        except Exception as e:
            self._send_error(500, f"Cannot read status: {e}")
    
    def _serve_status_png(self):
        """Serve status.png directly."""
        status_png = self.status_path.parent / "status.png"
        if not status_png.exists():
            self._send_error(404, "Status image not found")
            return
        
        try:
            content = status_png.read_bytes()
            self._send_file(content, content_type="image/png")
        except Exception as e:
            self._send_error(500, f"Cannot read status image: {e}")
    
    def _serve_sessions_list(self):
        """Serve a JSON list of available sessions."""
        sessions = self._list_sessions()
        content = json.dumps({"sessions": sessions}, indent=2)
        self._send_file(content.encode("utf-8"), content_type="application/json")
    
    def _serve_session_file(self, session_id: str, file_path: str):
        """Serve a file from a session directory."""
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists() or not session_dir.is_dir():
            self._send_error(404, f"Session not found: {session_id}")
            return
        
        # Security: prevent path traversal
        if ".." in file_path or file_path.startswith("/"):
            self._send_error(400, "Invalid path")
            return
        
        target_file = session_dir / file_path
        if not target_file.exists():
            self._send_error(404, f"File not found: {file_path}")
            return
        
        # Don't serve files outside the session directory
        try:
            target_file.resolve().relative_to(session_dir.resolve())
        except ValueError:
            self._send_error(403, "Access denied")
            return
        
        try:
            # Determine content type
            content_type = "application/octet-stream"
            if file_path.endswith(".html"):
                content_type = "text/html"
            elif file_path.endswith(".json"):
                content_type = "application/json"
            elif file_path.endswith(".png"):
                content_type = "image/png"
            elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                content_type = "image/jpeg"
            elif file_path.endswith(".txt"):
                content_type = "text/plain"
            
            if content_type.startswith("text/") or content_type == "application/json":
                content = target_file.read_text(encoding="utf-8", errors="replace")
                self._send_file(content.encode("utf-8"), content_type=content_type)
            else:
                content = target_file.read_bytes()
                self._send_file(content, content_type=content_type)
        except Exception as e:
            self._send_error(500, f"Cannot read file: {e}")
    
    def _redirect_to_session(self, session_id: str):
        """Redirect to session index.html."""
        self.send_response(302)
        self.send_header("Location", f"/sessions/{session_id}/index.html")
        self.end_headers()
    
    def _read_status_json(self) -> dict | None:
        """Read and parse status.json."""
        if not self.status_path.exists():
            return None
        try:
            content = self.status_path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception:
            return None
    
    def _list_sessions(self) -> list[str]:
        """List available session directories."""
        if not self.sessions_dir.exists():
            return []
        try:
            sessions = []
            for item in self.sessions_dir.iterdir():
                if item.is_dir():
                    # Check if it looks like a session directory (has index.html or share.txt)
                    if (item / "index.html").exists() or (item / "share.txt").exists():
                        sessions.append(item.name)
            return sorted(sessions, reverse=True)  # Most recent first
        except Exception:
            return []
    
    def _send_html(self, html: str):
        """Send HTML response."""
        self._send_file(html.encode("utf-8"), content_type="text/html")
    
    def _send_json(self, json_str: str):
        """Send JSON response."""
        self._send_file(json_str.encode("utf-8"), content_type="application/json")
    
    def _send_file(self, content: bytes, content_type: str = "application/octet-stream"):
        """Send file content with appropriate headers."""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")  # Don't cache status files
        self.end_headers()
        self.wfile.write(content)
    
    def _send_error(self, code: int, message: str):
        """Send error response."""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(f"{code} {message}\n".encode("utf-8"))


class GhostRollWebServer:
    """Lightweight web server for GhostRoll interface."""
    
    def __init__(
        self,
        *,
        status_path: Path,
        sessions_dir: Path,
        host: str = "127.0.0.1",
        port: int = 8080,
    ):
        self.status_path = status_path
        self.sessions_dir = sessions_dir
        self.host = host
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._running = False
    
    def start(self):
        """Start the web server in a background thread."""
        if self._running:
            return
        
        def handler_factory(*args, **kwargs):
            return GhostRollWebHandler(
                *args,
                status_path=self.status_path,
                sessions_dir=self.sessions_dir,
                **kwargs,
            )
        
        try:
            self.server = HTTPServer((self.host, self.port), handler_factory)
            self._running = True
            
            def run_server():
                try:
                    self.server.serve_forever()
                except Exception:
                    pass  # Server stopped
            
            self.thread = threading.Thread(target=run_server, daemon=True)
            self.thread.start()
            
            return True
        except OSError:
            # Port already in use or permission denied
            self._running = False
            return False
    
    def stop(self):
        """Stop the web server."""
        if not self._running:
            return
        
        self._running = False
        if self.server:
            self.server.shutdown()
            self.server.server_close()
    
    def get_url(self) -> str:
        """Get the URL where the server is accessible."""
        host_display = self.host if self.host != "127.0.0.1" else "localhost"
        return f"http://{host_display}:{self.port}"
    
    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running

