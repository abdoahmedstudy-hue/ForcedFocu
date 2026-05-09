#!/usr/bin/env python3
"""
ForcedFocus Web Server — HTTP API + static file server.
Bridges the web UI to the daemon via Unix socket.
Runs on localhost:7070 (not exposed to network).

⚠️  DEPRECATED: This standalone web server is REDUNDANT.
    The daemon (forcefocus_daemon.py) embeds its own HTTP server
    (EmbeddedHTTPServer + EmbeddedWebHandler) which is the canonical
    server started by the LaunchDaemon plist.

    This file is retained only for development/debugging purposes.
    It is NOT installed or started in production.
    Do NOT add new features here — use the daemon's embedded server instead.
"""

import os
import sys
import json
import socket
import time
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote

SOCK_PATH = "/var/run/forcefocus.sock"
WEB_DIR = Path("/usr/local/share/forcefocus/web")
HOST = "127.0.0.1"
PORT = 7070


def send_to_daemon(cmd: dict, retries: int = 3) -> dict:
    """Send a JSON command to the daemon via Unix socket."""
    last_error = None
    for attempt in range(retries):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect(SOCK_PATH)
            sock.sendall(json.dumps(cmd).encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)  # Signal end of message
            chunks = []
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                except socket.timeout:
                    break
            sock.close()
            raw = b"".join(chunks).decode("utf-8")
            return json.loads(raw)
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(1)
                continue
        except Exception as exc:
            return {"status": "error", "message": f"Daemon communication failed: {exc}"}
    return {"status": "daemon_starting", "message": f"Daemon not ready: {last_error}"}


class ForcedFocusHandler(BaseHTTPRequestHandler):
    """Handle HTTP requests for the ForcedFocus web UI."""

    def log_message(self, format, *args):
        """Suppress default logging noise."""
        pass

    def _is_origin_allowed(self) -> bool:
        """Check if the Origin header matches allowed origins."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in ("http://localhost:7070", "http://127.0.0.1:7070"):
            return True
        if origin == "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc":
            return True
        return False

    def _get_cors_origin(self) -> str:
        """Return the allowed origin for CORS headers."""
        origin = self.headers.get("Origin")
        if origin and (
            origin in ("http://localhost:7070", "http://127.0.0.1:7070")
            or origin == "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc"
        ):
            return origin
        return "http://127.0.0.1:7070"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: Path):
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return
        # Security: ensure path is under WEB_DIR
        try:
            filepath.resolve().relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return

        mime, _ = mimetypes.guess_type(str(filepath))
        if mime is None:
            mime = "application/octet-stream"

        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        MAX_BODY = 65536  # 64KB
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        if length > MAX_BODY:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    # ── Routes ────────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path.startswith("/api/") and not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        if path == "/api/status":
            self._send_json(send_to_daemon({"action": "status"}))
        elif path == "/api/lists":
            self._send_json(send_to_daemon({"action": "get_lists"}))
        elif path == "/api/groups":
            self._send_json(send_to_daemon({"action": "get_groups"}))
        elif path == "/" or path == "":
            self._send_file(WEB_DIR / "index.html")
        elif path == "/menubar":
            self._send_file(WEB_DIR / "menubar.html")
        else:
            # Serve static files
            safe_path = path.lstrip("/")
            self._send_file(WEB_DIR / safe_path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        body = self._read_body()

        if path == "/api/start":
            cmd = {
                "action": "start",
                "duration_minutes": body.get("duration", 120),
                "mode": body.get("mode", "blacklist"),
                "session_type": body.get("session_type", "standard"),
                "focus_minutes": body.get("focus_minutes", 25),
                "break_minutes": body.get("break_minutes", 5),
                "cycles": body.get("cycles", 4),
                "groups": body.get("groups", []),
            }
            if "schedule_in" in body:
                cmd["schedule_in_minutes"] = body["schedule_in"]
            if "schedule_at" in body:
                cmd["schedule_at_time"] = body["schedule_at"]
            self._send_json(send_to_daemon(cmd))

        elif path == "/api/stop":
            cmd = {"action": "stop", "key": body.get("key", "")}
            self._send_json(send_to_daemon(cmd))

        elif path.startswith("/api/lists/"):
            parts = path.strip("/").split("/")
            # /api/lists/blacklist/bulk
            if len(parts) == 4 and parts[3] == "bulk":
                list_name = parts[2]
                cmd = {
                    "action": "add_domains",
                    "list": list_name,
                    "domains": body.get("domains", []),
                }
                self._send_json(send_to_daemon(cmd))
            else:
                list_name = parts[-1]
                cmd = {
                    "action": "add_domain",
                    "list": list_name,
                    "domain": body.get("domain", ""),
                }
                self._send_json(send_to_daemon(cmd))

        elif path == "/api/groups":
            cmd = {
                "action": "add_group",
                "name": body.get("name", ""),
                "domains": body.get("domains", []),
            }
            self._send_json(send_to_daemon(cmd))

        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if not self._is_origin_allowed():
            self._send_json(
                {"status": "error", "message": "CORS policy: Origin not allowed."}, 403
            )
            return

        parts = path.strip("/").split("/")
        # /api/lists/blacklist/reddit.com
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "lists":
            list_name = parts[2]
            domain = "/".join(parts[3:])
            cmd = {
                "action": "remove_domain",
                "list": list_name,
                "domain": domain,
            }
            self._send_json(send_to_daemon(cmd))
        elif len(parts) == 3 and parts[0] == "api" and parts[1] == "groups":
            cmd = {
                "action": "remove_group",
                "name": parts[2],
            }
            self._send_json(send_to_daemon(cmd))
        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def main():
    # Allow running from source dir for development
    global WEB_DIR
    local_web = Path(__file__).parent / "web"
    if local_web.exists():
        WEB_DIR = local_web

    print(f"ForcedFocus Web UI starting at http://{HOST}:{PORT}")
    print(f"Serving files from: {WEB_DIR}")
    print("Press Ctrl+C to stop.\n")

    server = ReusableHTTPServer((HOST, PORT), ForcedFocusHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
