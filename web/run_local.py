"""
Run one ingestion from your own computer (same code the Vercel cron runs):

    python run_local.py                # all sites
    python run_local.py Ynet "Kan News"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_csv import load_env  # noqa: E402
from lib.ingest import run_ingest  # noqa: E402

if __name__ == "__main__":
    load_env()
    # RUN_TRIGGER names this run on the /logs page (the Kan workflow sets kan-action)
    trigger = os.environ.get("RUN_TRIGGER", "local")
    print(json.dumps(run_ingest(sys.argv[1:] or None, trigger=trigger), ensure_ascii=False, indent=2))
