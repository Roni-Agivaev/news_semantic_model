"""
Preview the dashboard locally against your database (no Vercel CLI needed):

    python dev_server.py        # then open http://localhost:8000
"""
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from api.stats import handler as StatsHandler  # noqa: E402
from import_csv import load_env  # noqa: E402


class DevHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/stats"):
            return StatsHandler.do_GET(self)
        return super().do_GET()


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(DevHandler, directory=os.path.join(HERE, "public")))
    print(f"Dashboard: http://localhost:{port}")
    server.serve_forever()
