"""
Lightweight web interface for GhostRoll.

Serves existing files (status.json, status.png, session galleries) with minimal overhead.
Designed to have virtually no performance impact on the main pipeline.
"""

from __future__ import annotations

import html as html_escape_module
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _get_git_info(repo_dir: Path | None = None) -> tuple[str | None, str | None]:
    """
    Get git commit hash and repository URL.
    
    Returns:
        Tuple of (commit_hash, repo_url) or (None, None) if not available.
    """
    try:
        # Try to determine repository directory
        if repo_dir is None:
            # Try to find the GhostRoll repo directory
            # Check common locations in order of preference
            possible_dirs = [
                Path(__file__).parent.parent,  # ghostroll/../ (repo root)
                Path("/home/pi/ghostroll"),    # Common Pi location
                Path("/usr/local/src/ghostroll"),  # Pi-gen location
                Path.cwd(),  # Current working directory (where Python was invoked)
            ]
            
            # Walk up from __file__ to find .git directory
            # This handles cases where the code is installed via pip install -e
            current = Path(__file__).parent
            for _ in range(5):  # Limit depth to avoid infinite loops
                if (current / ".git").exists():
                    possible_dirs.insert(0, current)
                    break
                parent = current.parent
                if parent == current:  # Reached root
                    break
                current = parent
            
            for candidate in possible_dirs:
                try:
                    if candidate.exists() and (candidate / ".git").exists():
                        repo_dir = candidate
                        break
                except (OSError, PermissionError):
                    # Skip directories we can't access
                    continue
        else:
            if not (repo_dir / ".git").exists():
                return None, None
        
        if repo_dir is None:
            return None, None
        
        # Get commit hash
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            commit_hash = result.stdout.strip() if result.returncode == 0 else None
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            commit_hash = None
        
        # Get repository URL
        repo_url = None
        if commit_hash:
            try:
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                if result.returncode == 0:
                    remote_url = result.stdout.strip()
                    # Convert SSH URLs to HTTPS URLs for GitHub
                    if remote_url.startswith("git@github.com:"):
                        repo_url = remote_url.replace("git@github.com:", "https://github.com/").replace(".git", "")
                    elif remote_url.startswith("https://github.com/"):
                        repo_url = remote_url.replace(".git", "")
                    else:
                        repo_url = remote_url.replace(".git", "")
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        
        return commit_hash, repo_url
    except Exception:
        return None, None


class GhostRollWebHandler(BaseHTTPRequestHandler):
    """HTTP request handler for GhostRoll web interface."""
    
    def __init__(self, *args, status_path: Path, sessions_dir: Path, git_info: tuple[str | None, str | None] = (None, None), **kwargs):
        self.status_path = status_path
        self.sessions_dir = sessions_dir
        self.git_info = git_info
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
<html lang="en">
<head>
    <title>GhostRoll</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta charset="utf-8">
    <style>
        :root {
            /* Dark mode (default) */
            --bg-primary: #0a0a0a;
            --bg-secondary: #1a1a1a;
            --bg-tertiary: #252525;
            --text-primary: #e0e0e0;
            --text-secondary: #b0b0b0;
            --text-tertiary: #888;
            --border: #333;
            --accent: #4a9eff;
            --accent-hover: #6bb0ff;
            --status-idle: #4a5568;
            --status-running: #f59e0b;
            --status-done: #10b981;
            --status-error: #ef4444;
            --shadow: rgba(0, 0, 0, 0.3);
        }
        
        @media (prefers-color-scheme: light) {
            :root {
                --bg-primary: #ffffff;
                --bg-secondary: #f8f9fa;
                --bg-tertiary: #e9ecef;
                --text-primary: #1a1a1a;
                --text-secondary: #4a5568;
                --text-tertiary: #6b7280;
                --border: #e5e7eb;
                --accent: #2563eb;
                --accent-hover: #3b82f6;
                --status-idle: #9ca3af;
                --status-running: #f59e0b;
                --status-done: #10b981;
                --status-error: #ef4444;
                --shadow: rgba(0, 0, 0, 0.1);
            }
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            min-height: 100vh;
            padding: 2rem 1rem;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
        }
        
        header {
            margin-bottom: 2.5rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px solid var(--border);
        }
        
        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent), var(--accent-hover));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 0.5rem;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 0.95rem;
        }
        
        .status-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            box-shadow: 0 4px 6px var(--shadow);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .status-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px var(--shadow);
        }
        
        .status-header {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            margin-bottom: 1rem;
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            flex-shrink: 0;
            animation: pulse 2s ease-in-out infinite;
        }
        
        .status-indicator.idle {
            background: var(--status-idle);
        }
        
        .status-indicator.running {
            background: var(--status-running);
        }
        
        .status-indicator.done {
            background: var(--status-done);
            animation: none;
        }
        
        .status-indicator.error {
            background: var(--status-error);
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .status-title {
            font-size: 1.25rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-primary);
        }
        
        .status-message {
            font-size: 1.1rem;
            color: var(--text-primary);
            margin-bottom: 1rem;
            font-weight: 500;
        }
        
        .status-details {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin-top: 1rem;
        }
        
        .detail-item {
            flex: 1;
            min-width: 150px;
        }
        
        .detail-label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 0.25rem;
        }
        
        .detail-value {
            font-size: 1rem;
            color: var(--text-primary);
            font-weight: 500;
            word-break: break-all;
        }
        
        .detail-value code {
            background: var(--bg-tertiary);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
            font-size: 0.9em;
            color: var(--accent);
        }
        
        .status-counts {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            margin-top: 1rem;
        }
        
        .count-badge {
            background: var(--bg-tertiary);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.9rem;
            border: 1px solid var(--border);
        }
        
        .count-label {
            color: var(--text-secondary);
            font-size: 0.85rem;
        }
        
        .count-value {
            color: var(--accent);
            font-weight: 600;
            font-size: 1.1rem;
        }
        
        .action-button {
            display: inline-block;
            margin-top: 1rem;
            padding: 0.75rem 1.5rem;
            background: var(--accent);
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 500;
            transition: background 0.2s ease, transform 0.1s ease;
            box-shadow: 0 2px 4px var(--shadow);
        }
        
        .action-button:hover {
            background: var(--accent-hover);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px var(--shadow);
        }
        
        .sessions-section {
            margin-top: 3rem;
        }
        
        .section-title {
            font-size: 1.5rem;
            font-weight: 600;
            margin-bottom: 1.5rem;
            color: var(--text-primary);
        }
        
        .sessions-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 1rem;
        }
        
        .session-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1.25rem;
            transition: all 0.2s ease;
            cursor: pointer;
            text-decoration: none;
            color: inherit;
            display: block;
        }
        
        .session-card:hover {
            border-color: var(--accent);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px var(--shadow);
        }
        
        .session-id {
            font-family: "SF Mono", Monaco, monospace;
            font-size: 0.9rem;
            color: var(--text-primary);
            font-weight: 500;
            word-break: break-all;
        }
        
        .session-icon {
            display: inline-block;
            margin-right: 0.5rem;
            font-size: 1.2rem;
        }
        
        .footer {
            margin-top: 3rem;
            padding-top: 2rem;
            border-top: 1px solid var(--border);
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
        }
        
        .footer-link {
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 0.9rem;
            transition: color 0.2s ease;
        }
        
        .footer-link:hover {
            color: var(--accent);
        }
        
        .version-link {
            font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
            font-size: 0.85rem;
        }
        
        .version-link code {
            background: var(--bg-tertiary);
            padding: 0.2rem 0.4rem;
            border-radius: 4px;
            font-family: inherit;
            font-size: inherit;
            color: var(--text-secondary);
            transition: all 0.2s ease;
        }
        
        .version-link:hover code {
            background: var(--accent);
            color: white;
        }
        
        .empty-state {
            text-align: center;
            padding: 3rem 1rem;
            color: var(--text-secondary);
        }
        
        .empty-state-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            opacity: 0.5;
        }
        
        .qr-section {
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.75rem;
        }
        
        .qr-title {
            font-size: 0.9rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }
        
        .qr-code {
            width: 160px;
            height: 160px;
            border-radius: 12px;
            border: 2px solid var(--border);
            padding: 8px;
            background: white;
            box-shadow: 0 4px 12px var(--shadow);
            display: block;
        }
        
        .qr-code img {
            width: 100%;
            height: 100%;
            object-fit: contain;
            display: block;
        }
        
        .qr-hint {
            font-size: 0.85rem;
            color: var(--text-tertiary);
            text-align: center;
        }
        
        .progress-section {
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
        }
        
        .progress-item {
            margin-bottom: 1rem;
        }
        
        .progress-item:last-child {
            margin-bottom: 0;
        }
        
        .progress-label {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            color: var(--text-secondary);
        }
        
        .progress-label-text {
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .progress-label-value {
            font-family: "SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace;
            color: var(--accent);
            font-weight: 600;
        }
        
        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: var(--bg-tertiary);
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }
        
        .progress-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent), var(--accent-hover));
            border-radius: 4px;
            transition: width 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        
        .progress-bar-fill::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            bottom: 0;
            right: 0;
            background: linear-gradient(
                90deg,
                transparent,
                rgba(255, 255, 255, 0.2),
                transparent
            );
            animation: shimmer 2s infinite;
        }
        
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        
        .progress-bar-fill.complete {
            background: var(--status-done);
        }
        
        .progress-bar-fill.complete::after {
            display: none;
        }
        
        @media (max-width: 640px) {
            h1 {
                font-size: 2rem;
            }
            
            .container {
                padding: 0;
            }
            
            .sessions-grid {
                grid-template-columns: 1fr;
            }
            
            .status-details {
                flex-direction: column;
                gap: 1rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>GhostRoll</h1>
            <p class="subtitle">Image ingest pipeline & gallery</p>
        </header>
"""
        
        if status_data:
            state = status_data.get("state", "unknown").lower()
            state_display = state.upper()
            message = status_data.get("message", "")
            session_id = status_data.get("session_id")
            url = status_data.get("url")
            counts = status_data.get("counts") or {}
            volume = status_data.get("volume")
            
            # Fallback: If URL is not set but we have a session_id, try to read from share.txt
            if not url and session_id:
                share_txt = self.sessions_dir / session_id / "share.txt"
                if share_txt.exists() and share_txt.is_file():
                    try:
                        url = share_txt.read_text(encoding="utf-8").strip()
                        # Only use if it's a valid S3 presigned URL (starts with https://)
                        if url and url.startswith("https://"):
                            pass  # Valid URL, use it
                        else:
                            url = None  # Invalid URL, ignore it
                    except Exception:
                        pass  # Failed to read, keep url as None
            
            html += '        <div class="status-card">\n'
            html += '            <div class="status-header">\n'
            html += f'                <div class="status-indicator {state}"></div>\n'
            html += f'                <div class="status-title">{state_display}</div>\n'
            html += '            </div>\n'
            
            if message:
                html += f'            <div class="status-message">{message}</div>\n'
            
            html += '            <div class="status-details">\n'
            
            if session_id:
                html += '                <div class="detail-item">\n'
                html += '                    <div class="detail-label">Session</div>\n'
                html += f'                    <div class="detail-value"><code>{session_id}</code></div>\n'
                html += '                </div>\n'
            
            if volume:
                vol_name = volume.split("/")[-1]
                html += '                <div class="detail-item">\n'
                html += '                    <div class="detail-label">Volume</div>\n'
                html += f'                    <div class="detail-value">{vol_name}</div>\n'
                html += '                </div>\n'
            
            html += '            </div>\n'
            
            if counts:
                html += '            <div class="status-counts">\n'
                for key, value in sorted(counts.items()):
                    key_display = key.replace("_", " ").title()
                    html += f'                <div class="count-badge">\n'
                    html += f'                    <div class="count-label">{key_display}</div>\n'
                    html += f'                    <div class="count-value">{value}</div>\n'
                    html += '                </div>\n'
                html += '            </div>\n'
            
            # Add progress bars section (will be populated by JavaScript)
            html += '            <div class="progress-section" id="progress-section" style="display: none;">\n'
            html += '            </div>\n'
            
            if url:
                html += f'            <a href="{url}" target="_blank" class="action-button">View Gallery →</a>\n'
            
            # Add QR code if available
            qr_path_str = status_data.get("qr_path")
            if qr_path_str and url:
                # Check if QR code file exists and is accessible
                qr_path = Path(qr_path_str)
                if qr_path.exists() and qr_path.is_file() and qr_path.stat().st_size > 0:
                    # Determine QR code URL
                    qr_url = None
                    if session_id:
                        # QR code is in session directory, use session path
                        # Verify that the QR path is actually in the session directory
                        try:
                            qr_path_relative = qr_path.resolve().relative_to(
                                (self.sessions_dir / session_id).resolve()
                            )
                            if qr_path_relative == Path("share-qr.png"):
                                qr_url = f"/sessions/{session_id}/share-qr.png"
                        except (ValueError, OSError):
                            # QR path is not in session directory, skip
                            pass
                    
                    if qr_url:
                        html += '            <div class="qr-section">\n'
                        html += '                <div class="qr-title">Scan to Open Gallery</div>\n'
                        html += f'                <a href="{html_escape_module.escape(url)}" target="_blank" class="qr-code" aria-label="QR code for gallery link">\n'
                        html += f'                    <img src="{html_escape_module.escape(qr_url)}" alt="QR code" loading="lazy">\n'
                        html += '                </a>\n'
                        html += '                <div class="qr-hint">Point your phone camera at the code</div>\n'
                        html += '            </div>\n'
            
            html += '        </div>\n'
        else:
            html += '        <div class="status-card">\n'
            html += '            <div class="status-header">\n'
            html += '                <div class="status-indicator idle"></div>\n'
            html += '                <div class="status-title">Unknown</div>\n'
            html += '            </div>\n'
            html += '            <div class="status-message">Status file not found</div>\n'
            html += '        </div>\n'
        
        # List sessions
        sessions = self._list_sessions()
        if sessions:
            html += '        <div class="sessions-section">\n'
            html += '            <h2 class="section-title">Sessions</h2>\n'
            html += '            <div class="sessions-grid">\n'
            for session_id in sessions:
                html += f'                <a href="/sessions/{session_id}" class="session-card">\n'
                html += '                    <span class="session-icon">📷</span>\n'
                html += f'                    <span class="session-id">{session_id}</span>\n'
                html += '                </a>\n'
            html += '            </div>\n'
            html += '        </div>\n'
        else:
            html += '        <div class="sessions-section">\n'
            html += '            <h2 class="section-title">Sessions</h2>\n'
            html += '            <div class="empty-state">\n'
            html += '                <div class="empty-state-icon">📂</div>\n'
            html += '                <p>No sessions found yet</p>\n'
            html += '            </div>\n'
            html += '        </div>\n'
        
        html += '        <div class="footer">\n'
        html += '            <a href="/status.json" class="footer-link">Status JSON</a>\n'
        html += '            <a href="/status.png" class="footer-link">Status Image</a>\n'
        html += '            <a href="/sessions" class="footer-link">Sessions API</a>\n'
        
        # Add log link if there's an active session
        if status_data:
            session_id = status_data.get("session_id")
            if session_id:
                log_file = self.sessions_dir / session_id / "ghostroll.log"
                if log_file.exists() and log_file.is_file():
                    log_url = f"/sessions/{session_id}/ghostroll.log"
                    html += f'            <a href="{html_escape_module.escape(log_url)}" class="footer-link" target="_blank" title="View session log">📋 Log</a>\n'
        
        # Add git commit hash with link if available (use cached info from server startup)
        commit_hash, repo_url = self.git_info
        if commit_hash:
            short_hash = commit_hash[:7]
            if repo_url:
                commit_url = f"{repo_url}/commit/{commit_hash}"
                html += f'            <a href="{html_escape_module.escape(commit_url)}" target="_blank" class="footer-link version-link" title="Commit: {html_escape_module.escape(commit_hash)}">'
                html += f'            <code>{html_escape_module.escape(short_hash)}</code></a>\n'
            else:
                html += f'            <span class="footer-link version-link" title="Commit: {html_escape_module.escape(commit_hash)}">'
                html += f'            <code>{html_escape_module.escape(short_hash)}</code></span>\n'
        
        html += '        </div>\n'
        html += '    </div>\n'
        
        # Add auto-refresh JavaScript to poll status.json and update the display
        html += """        <script>
        (function() {
            const STATUS_URL = '/status.json';
            const POLL_INTERVAL = 2000; // Poll every 2 seconds
            let currentSessionId = null;
            let currentUrl = null;
            let pollTimer = null;
            
            // Elements that will be updated
            let statusCard = null;
            let statusIndicator = null;
            let statusTitle = null;
            let statusMessage = null;
            let statusDetails = null;
            let statusCounts = null;
            let qrSection = null;
            
            function initElements() {
                statusCard = document.querySelector('.status-card');
                if (!statusCard) return false;
                statusIndicator = statusCard.querySelector('.status-indicator');
                statusTitle = statusCard.querySelector('.status-title');
                statusMessage = statusCard.querySelector('.status-message');
                statusDetails = statusCard.querySelector('.status-details');
                statusCounts = statusCard.querySelector('.status-counts');
                qrSection = statusCard.querySelector('.qr-section');
                return true;
            }
            
            function updateStatus(data) {
                if (!statusCard || !data) return;
                
                const state = (data.state || 'unknown').toLowerCase();
                const stateDisplay = state.toUpperCase();
                const message = data.message || '';
                const sessionId = data.session_id || null;
                let url = data.url || null;
                const counts = data.counts || {};
                const volume = data.volume || null;
                
                // Fallback: If URL is not set but we have a sessionId, try to fetch from share.txt
                if (!url && sessionId) {
                    fetch('/sessions/' + escapeHtml(sessionId) + '/share.txt')
                        .then(response => {
                            if (response.ok) {
                                return response.text();
                            }
                            return null;
                        })
                        .then(shareUrl => {
                            if (shareUrl && shareUrl.trim()) {
                                url = shareUrl.trim();
                                // Update the button and QR code with the fetched URL
                                updateGalleryLinks(url, sessionId, data.qr_path || null);
                            }
                        })
                        .catch(() => {
                            // Ignore errors - URL will remain null
                        });
                }
                
                // Update status indicator and title
                if (statusIndicator) {
                    statusIndicator.className = 'status-indicator ' + state;
                }
                if (statusTitle) {
                    statusTitle.textContent = stateDisplay;
                }
                
                // Update message
                if (statusMessage) {
                    if (message) {
                        statusMessage.textContent = message;
                        statusMessage.style.display = '';
                    } else {
                        statusMessage.style.display = 'none';
                    }
                }
                
                // Update details (session, volume)
                if (statusDetails) {
                    let detailsHTML = '';
                    if (sessionId) {
                        detailsHTML += '<div class="detail-item">\\n';
                        detailsHTML += '    <div class="detail-label">Session</div>\\n';
                        detailsHTML += '    <div class="detail-value"><code>' + escapeHtml(sessionId) + '</code></div>\\n';
                        detailsHTML += '</div>\\n';
                    }
                    if (volume) {
                        const volName = volume.split('/').pop();
                        detailsHTML += '<div class="detail-item">\\n';
                        detailsHTML += '    <div class="detail-label">Volume</div>\\n';
                        detailsHTML += '    <div class="detail-value">' + escapeHtml(volName) + '</div>\\n';
                        detailsHTML += '</div>\\n';
                    }
                    statusDetails.innerHTML = detailsHTML || '';
                }
                
                // Update counts
                if (statusCounts) {
                    if (Object.keys(counts).length > 0) {
                        let countsHTML = '';
                        for (const [key, value] of Object.entries(counts).sort()) {
                            const keyDisplay = key.replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
                            countsHTML += '<div class="count-badge">\\n';
                            countsHTML += '    <div class="count-label">' + escapeHtml(keyDisplay) + '</div>\\n';
                            countsHTML += '    <div class="count-value">' + escapeHtml(String(value)) + '</div>\\n';
                            countsHTML += '</div>\\n';
                        }
                        statusCounts.innerHTML = countsHTML;
                        statusCounts.style.display = 'flex';
                    } else {
                        statusCounts.style.display = 'none';
                    }
                }
                
                // Update progress bars
                updateProgressBars(counts, state);
                
                // Update gallery links (button and QR code)
                updateGalleryLinks(url, sessionId, data.qr_path || null);
            }
            
            function updateGalleryLinks(url, sessionId, qrPathStr) {
                // Update action button (gallery link)
                let actionButton = statusCard.querySelector('.action-button');
                if (url) {
                    // Ensure URL is the presigned S3 URL, not a local path
                    // If it looks like a local path (/sessions/...), don't use it
                    if (url.startsWith('/sessions/') || url.startsWith('http://localhost') || url.startsWith('http://127.0.0.1')) {
                        // This is a local path, not the S3 presigned URL - skip it
                        if (actionButton) {
                            actionButton.style.display = 'none';
                        }
                        return;
                    }
                    
                    if (!actionButton) {
                        // Create button if it doesn't exist
                        const buttonContainer = document.createElement('div');
                        buttonContainer.style.marginTop = '1rem';
                        statusCard.appendChild(buttonContainer);
                        actionButton = document.createElement('a');
                        actionButton.className = 'action-button';
                        actionButton.target = '_blank';
                        buttonContainer.appendChild(actionButton);
                    }
                    actionButton.href = url;
                    actionButton.textContent = 'View Gallery →';
                    actionButton.style.display = 'inline-block';
                } else if (actionButton) {
                    actionButton.style.display = 'none';
                }
                
                // Update QR code if URL or session changed
                if (url && sessionId && qrPathStr) {
                    // Ensure URL is the presigned S3 URL, not a local path
                    if (url.startsWith('/sessions/') || url.startsWith('http://localhost') || url.startsWith('http://127.0.0.1')) {
                        // This is a local path, not the S3 presigned URL - skip QR code
                        if (qrSection) {
                            qrSection.remove();
                            qrSection = null;
                        }
                        currentSessionId = null;
                        currentUrl = null;
                        return;
                    }
                    
                    const qrUrl = '/sessions/' + escapeHtml(sessionId) + '/share-qr.png';
                    
                    // Only update QR if session or URL changed
                    if (sessionId !== currentSessionId || url !== currentUrl) {
                        currentSessionId = sessionId;
                        currentUrl = url;
                        
                        // Remove existing QR section
                        if (qrSection) {
                            qrSection.remove();
                            qrSection = null;
                        }
                        
                        // Create new QR section
                        const qrDiv = document.createElement('div');
                        qrDiv.className = 'qr-section';
                        qrDiv.innerHTML = 
                            '<div class="qr-title">Scan to Open Gallery</div>\\n' +
                            '<a href="' + escapeHtml(url) + '" target="_blank" class="qr-code" aria-label="QR code for gallery link">\\n' +
                            '    <img src="' + escapeHtml(qrUrl) + '" alt="QR code" loading="lazy">\\n' +
                            '</a>\\n' +
                            '<div class="qr-hint">Point your phone camera at the code</div>';
                        statusCard.appendChild(qrDiv);
                        qrSection = qrDiv;
                    }
                } else {
                    // Remove QR section if no URL/session
                    if (qrSection) {
                        qrSection.remove();
                        qrSection = null;
                    }
                    currentSessionId = null;
                    currentUrl = null;
                }
            }
            
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            function updateProgressBars(counts, state) {
                if (!statusCard) return;
                
                let progressSection = statusCard.querySelector('#progress-section');
                if (!progressSection) {
                    // Create progress section if it doesn't exist
                    progressSection = document.createElement('div');
                    progressSection.id = 'progress-section';
                    progressSection.className = 'progress-section';
                    // Insert before QR section or at end of status card
                    const qrSection = statusCard.querySelector('.qr-section');
                    if (qrSection) {
                        statusCard.insertBefore(progressSection, qrSection);
                    } else {
                        statusCard.appendChild(progressSection);
                    }
                }
                
                const progressItems = [];
                
                // Processing progress
                if (counts.processed_done !== undefined && counts.processed_total !== undefined && counts.processed_total > 0) {
                    const done = parseInt(counts.processed_done) || 0;
                    const total = parseInt(counts.processed_total) || 0;
                    const percent = Math.min(100, Math.round((done / total) * 100));
                    const isComplete = done >= total;
                    progressItems.push({
                        label: 'Processing',
                        done: done,
                        total: total,
                        percent: percent,
                        complete: isComplete
                    });
                }
                
                // Upload progress
                if (counts.uploaded_done !== undefined && counts.uploaded_total !== undefined && counts.uploaded_total > 0) {
                    const done = parseInt(counts.uploaded_done) || 0;
                    const total = parseInt(counts.uploaded_total) || 0;
                    const percent = Math.min(100, Math.round((done / total) * 100));
                    const isComplete = done >= total;
                    progressItems.push({
                        label: 'Uploading',
                        done: done,
                        total: total,
                        percent: percent,
                        complete: isComplete
                    });
                }
                
                // Presigning progress (if available)
                if (counts.presigned_done !== undefined && counts.presigned_total !== undefined && counts.presigned_total > 0) {
                    const done = parseInt(counts.presigned_done) || 0;
                    const total = parseInt(counts.presigned_total) || 0;
                    const percent = Math.min(100, Math.round((done / total) * 100));
                    const isComplete = done >= total;
                    progressItems.push({
                        label: 'Generating Links',
                        done: done,
                        total: total,
                        percent: percent,
                        complete: isComplete
                    });
                }
                
                // Render progress bars
                if (progressItems.length > 0 && state === 'running') {
                    let progressHTML = '';
                    for (const item of progressItems) {
                        progressHTML += '<div class="progress-item">\\n';
                        progressHTML += '    <div class="progress-label">\\n';
                        progressHTML += '        <span class="progress-label-text">' + escapeHtml(item.label) + '</span>\\n';
                        progressHTML += '        <span class="progress-label-value">' + item.done + ' / ' + item.total + ' (' + item.percent + '%)</span>\\n';
                        progressHTML += '    </div>\\n';
                        progressHTML += '    <div class="progress-bar-container">\\n';
                        const fillClass = item.complete ? 'progress-bar-fill complete' : 'progress-bar-fill';
                        progressHTML += '        <div class="' + fillClass + '" style="width: ' + item.percent + '%;"></div>\\n';
                        progressHTML += '    </div>\\n';
                        progressHTML += '</div>\\n';
                    }
                    progressSection.innerHTML = progressHTML;
                    progressSection.style.display = '';
                } else {
                    progressSection.style.display = 'none';
                }
            }
            
            async function pollStatus() {
                try {
                    const response = await fetch(STATUS_URL, {
                        cache: 'no-store',
                        headers: {
                            'Cache-Control': 'no-cache'
                        }
                    });
                    if (!response.ok) {
                        throw new Error('Status fetch failed: ' + response.status);
                    }
                    const data = await response.json();
                    updateStatus(data);
                } catch (error) {
                    // Silently handle errors - don't spam console
                    // The page will just show the last known status
                }
            }
            
            function startPolling() {
                if (!initElements()) {
                    // Retry after a short delay if elements aren't ready yet
                    setTimeout(startPolling, 500);
                    return;
                }
                
                // Poll immediately, then on interval
                pollStatus();
                pollTimer = setInterval(pollStatus, POLL_INTERVAL);
                
                // Stop polling when page is hidden (save resources)
                document.addEventListener('visibilitychange', function() {
                    if (document.hidden) {
                        if (pollTimer) {
                            clearInterval(pollTimer);
                            pollTimer = null;
                        }
                    } else {
                        if (!pollTimer) {
                            pollStatus();
                            pollTimer = setInterval(pollStatus, POLL_INTERVAL);
                        }
                    }
                });
            }
            
            // Start when DOM is ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', startPolling);
            } else {
                startPolling();
            }
        })();
        </script>
        """
        
        html += '    </div>\n'
        html += '</body>\n'
        html += '</html>'
        
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
            elif file_path.endswith(".log"):
                content_type = "text/plain; charset=utf-8"
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
        # Cache git info at startup to avoid calling git on every request
        self._cached_git_info: tuple[str | None, str | None] = _get_git_info()
        # Log git info for debugging
        commit_hash, repo_url = self._cached_git_info
        if commit_hash:
            short_hash = commit_hash[:7]
            import sys
            if repo_url:
                print(f"ghostroll-web: Git commit: {short_hash} (repo: {repo_url})", file=sys.stderr)
            else:
                print(f"ghostroll-web: Git commit: {short_hash} (no repo URL)", file=sys.stderr)
        else:
            import sys
            print("ghostroll-web: Git info not available (not in a git repo or git not installed)", file=sys.stderr)
    
    def start(self):
        """Start the web server in a background thread."""
        if self._running:
            return True
        
        def handler_factory(*args, **kwargs):
            return GhostRollWebHandler(
                *args,
                status_path=self.status_path,
                sessions_dir=self.sessions_dir,
                git_info=self._cached_git_info,
                **kwargs,
            )
        
        try:
            self.server = HTTPServer((self.host, self.port), handler_factory)
            self._running = True
            
            def run_server():
                try:
                    self.server.serve_forever()
                except Exception as e:
                    # Log server errors (if server was stopped, this is expected)
                    import sys
                    if self._running:  # Only log if it wasn't intentionally stopped
                        print(f"ghostroll-web: server error: {e}", file=sys.stderr)
            
            self.thread = threading.Thread(target=run_server, daemon=True)
            self.thread.start()
            
            # Give the server a moment to start and verify it's actually running
            import time
            time.sleep(0.1)
            if not self._running:
                return False
            
            return True
        except OSError as e:
            # Port already in use or permission denied
            import sys
            print(f"ghostroll-web: failed to start on {self.host}:{self.port}: {e}", file=sys.stderr)
            self._running = False
            return False
        except Exception as e:
            import sys
            print(f"ghostroll-web: unexpected error starting server: {e}", file=sys.stderr)
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

