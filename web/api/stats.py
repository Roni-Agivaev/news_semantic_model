"""
GET /api/stats?by=ingested|published&days=30 — article counts for the dashboard.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        by = "published" if query.get("by", [""])[0] == "published" else "ingested"
        try:
            days = int(query.get("days", ["30"])[0])
            days = 0 if days <= 0 else min(days, 365)  # 0 = all time
        except ValueError:
            days = 30

        try:
            conn = db.connect()
            try:
                body = db.stats(conn, by=by, days=days)
            finally:
                conn.close()
            status = 200
        except Exception as e:
            body, status = {"error": f"{type(e).__name__}: {e}"}, 500

        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "s-maxage=60, stale-while-revalidate=300")
        self.end_headers()
        self.wfile.write(data)
