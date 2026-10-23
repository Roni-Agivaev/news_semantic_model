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

from api.login import handler as LoginHandler  # noqa: E402
from api.stats import handler as StatsHandler  # noqa: E402
from import_csv import load_env  # noqa: E402


def delegate(request, api_class, method):
    """Run a Vercel API handler's method on this request, with that handler's helpers bound."""
    for name, attr in vars(api_class).items():
        if name.startswith("_") and not name.startswith("__") and callable(attr):
            setattr(request, name, attr.__get__(request))
    return getattr(api_class, method)(request)


class DevHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/stats"):
            return delegate(self, StatsHandler, "do_GET")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/login"):
            return delegate(self, LoginHandler, "do_POST")
        self.send_error(404)


if __name__ == "__main__":
    load_env()
    port = int(os.environ.get("PORT", 8000))
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(DevHandler, directory=os.path.join(HERE, "public")))
    print(f"Dashboard: http://localhost:{port}")
    server.serve_forever()
