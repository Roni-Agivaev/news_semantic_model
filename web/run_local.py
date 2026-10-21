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
    print(json.dumps(run_ingest(sys.argv[1:] or None), ensure_ascii=False, indent=2))
