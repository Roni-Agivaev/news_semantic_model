"""
GET /api/logs            recent scrape runs (newest first) plus the newest run's events
GET /api/logs?run=<id>   the same, with that run's events instead
Feeds the /logs page. Requires the login cookie.
"""
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import auth, db  # noqa: E402

RUN_ID = re.compile(r"^[0-9a-f]{6,32}$")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if not auth.is_logged_in(self.headers):
            return self._send(401, {"error": "login required"})

        run_id = parse_qs(urlparse(self.path).query).get("run", [""])[0]
        if run_id and not RUN_ID.match(run_id):
            return self._send(400, {"error": "bad run id"})
        try:
            conn = db.connect()
            try:
                # One round trip for the page: the run list plus the chosen run
                # (or the newest one when none is named).
                runs = db.list_scrape_runs(conn)
                chosen = run_id or (runs[0]["id"] if runs else None)
                detail = db.get_scrape_run(conn, chosen) if chosen else None
                body = {"runs": runs, "run": detail and detail["run"], "events": detail["events"] if detail else []}
            finally:
                conn.close()
            status = 200
        except Exception as e:
            body, status = {"error": f"{type(e).__name__}: {e}"}, 500
        self._send(status, body)

    def _send(self, status, body):
        iso = lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)  # noqa: E731
        data = json.dumps(body, ensure_ascii=False, default=iso).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()
        self.wfile.write(data)
