"""
GET /api/cron — runs one ingestion of all sites.

Vercel Cron calls this once a day (see vercel.json) and automatically sends
"Authorization: Bearer $CRON_SECRET". Any request without that header is refused.
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.ingest import run_ingest  # noqa: E402
from lib.scraper import SITES  # noqa: E402

# Sites that block Vercel's IPs are scraped from a local machine instead.
SERVER_SOURCES = [s for s, site in SITES.items() if not site.get("server_blocked")]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        secret = os.environ.get("CRON_SECRET")
        given = self.headers.get("Authorization", "")
        if not secret or not hmac.compare_digest(given, f"Bearer {secret}"):
            return self._send(401, {"error": "unauthorized"})

        try:
            result = run_ingest(SERVER_SOURCES)
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        self._send(200, result)

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
