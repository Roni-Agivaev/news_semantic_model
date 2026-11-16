"""
GET /api/stats?topic=defense|politics&section=&by=ingested|published&days=30
Article counts for the dashboard.
Requires the login cookie (see api/login.py).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import auth, db  # noqa: E402
from lib.params import topic_and_section  # noqa: E402
from lib.scraper import sources as topic_sources  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not auth.is_logged_in(self.headers):
            return self._send(401, {"error": "login required"})

        query = parse_qs(urlparse(self.path).query)
        topic, section = topic_and_section({k: v[0] for k, v in query.items()})
        if topic is None:
            return self._send(400, {"error": "unknown topic"})
        by = "published" if query.get("by", [""])[0] == "published" else "ingested"
        try:
            days = int(query.get("days", ["30"])[0])
            days = 0 if days <= 0 else min(days, 365)  # 0 = all time
        except ValueError:
            days = 30

        try:
            conn = db.connect()
            try:
                body = db.stats(conn, by=by, days=days, topic=topic, section=section,
                                sources=topic_sources(topic))
            finally:
                conn.close()
            status = 200
        except Exception as e:
            body, status = {"error": f"{type(e).__name__}: {e}"}, 500
        self._send(status, body)

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Per-user data: never cache it on Vercel's shared CDN
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)
