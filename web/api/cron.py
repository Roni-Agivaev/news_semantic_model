"""
/api/cron — runs one ingestion of the sources Vercel can reach.

GET:  Vercel Cron calls this once a day per topic (see vercel.json:
      /api/cron?topic=defense and /api/cron?topic=politics) and automatically
      sends "Authorization: Bearer $CRON_SECRET". Any request without that
      header is refused. No topic means defense.
POST: the dashboard's "Ingest now" button, for a signed-in user (lib/auth.py).
      Runs both topics, one after the other, and also starts Kan's GitHub
      workflow when GITHUB_TOKEN is set (lib/github.py).
"""
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import auth  # noqa: E402
from lib.github import start_kan_workflow  # noqa: E402
from lib.ingest import run_ingest  # noqa: E402
from lib.scraper import TOPICS, server_sources  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        secret = os.environ.get("CRON_SECRET")
        given = self.headers.get("Authorization", "")
        if not secret or not hmac.compare_digest(given, f"Bearer {secret}"):
            return self._send(401, {"error": "unauthorized"})
        topic = parse_qs(urlparse(self.path).query).get("topic", ["defense"])[0]
        if topic not in TOPICS:
            return self._send(400, {"error": f"unknown topic; expected one of {', '.join(TOPICS)}"})
        try:
            result = run_ingest(topic, server_sources(topic), trigger="cron")
        except Exception as e:
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})
        self._send(200, result)

    def do_POST(self):
        if not auth.is_logged_in(self.headers):
            return self._send(401, {"error": "login required"})
        # Start Kan first: GitHub needs a minute to spin up, so it runs while we scrape.
        kan_started, kan_message = start_kan_workflow()
        runs = []
        for topic in TOPICS:
            try:
                runs.append(run_ingest(topic, server_sources(topic), trigger="manual"))
            except Exception as e:
                runs.append({"topic": topic, "error": f"{type(e).__name__}: {e}", "sites": [], "new_articles": 0})
        self._send(200, {"runs": runs, "new_articles": sum(r["new_articles"] for r in runs),
                         "kan": {"started": kan_started, "message": kan_message}})

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
