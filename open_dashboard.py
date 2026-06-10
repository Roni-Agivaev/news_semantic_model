"""
Opens the News Sentiment Dashboard in your browser.
Just run: python open_dashboard.py
"""
import http.server
import threading
import webbrowser
import os

PORT = 8080
DIR = os.path.dirname(os.path.abspath(__file__))

os.chdir(DIR)

handler = http.server.SimpleHTTPRequestHandler
server = http.server.HTTPServer(("localhost", PORT), handler)

print(f"Dashboard running at http://localhost:{PORT}/dashboard/index.html")
print("Press Ctrl+C to stop.\n")

# Open browser after a short delay
threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{PORT}/dashboard/index.html")).start()

try:
    server.serve_forever()
except KeyboardInterrupt:
    print("\nServer stopped.")
    server.shutdown()
