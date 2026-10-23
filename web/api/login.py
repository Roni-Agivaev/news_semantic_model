"""
POST /api/login   body {"password": "..."}  -> sets the session cookie
POST /api/login?logout=1                     -> clears it
"""
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import auth  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if "logout" in parse_qs(urlparse(self.path).query):
            return self._send(200, {"ok": True}, auth.logout_cookie())

        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(length, 4096)) or b"{}")
            password = body.get("password", "")
        except (ValueError, AttributeError):
            password = ""

        if auth.check_password(password):
            return self._send(200, {"ok": True}, auth.login_cookie())
        time.sleep(1)  # slow down guessing
        self._send(401, {"error": "wrong password"})

    def _send(self, status, body, cookie=None):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)
