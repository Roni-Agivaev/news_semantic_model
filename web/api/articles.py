"""
GET /api/articles?q=&source=&from=YYYY-MM-DD&to=YYYY-MM-DD&limit=50&offset=0
One page of stored articles for the dashboard's explorer. Requires the login cookie.
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import auth, db  # noqa: E402

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not auth.is_logged_in(self.headers):
            return self._send(401, {"error": "login required"})

        query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        date = lambda k: query.get(k) if DATE.match(query.get(k, "")) else None  # noqa: E731
        try:
            conn = db.connect()
            try:
                body = db.search_articles(
                    conn,
                    q=query.get("q", "").strip()[:200],
                    source=query.get("source", ""),
                    date_from=date("from"),
                    date_to=date("to"),
                    limit=_int(query.get("limit"), 50, 1, 200),
                    offset=_int(query.get("offset"), 0, 0, 1_000_000),
                )
            finally:
                conn.close()
            status = 200
        except Exception as e:
            body, status = {"error": f"{type(e).__name__}: {e}"}, 500
        self._send(status, body)

    def _send(self, status, body):
        # ISO timestamps (with a "T"), which every browser's Date() parses
        iso = lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)  # noqa: E731
        data = json.dumps(body, ensure_ascii=False, default=iso).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)
