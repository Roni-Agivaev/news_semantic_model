"""
Run one ingestion from your own computer (same code the Vercel cron runs):

    python run_local.py                              # defense, every source
    python run_local.py --topic politics             # politics, every source
    python run_local.py --topic politics "Kan News"  # named sources only

RUN_TOPIC and RUN_TRIGGER (environment) set the default topic and how the run
is named on the /logs page; the Kan workflow sets RUN_TRIGGER=kan-action.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_csv import load_env  # noqa: E402
from lib.ingest import run_ingest  # noqa: E402
from lib.scraper import TOPICS  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--topic", choices=TOPICS, default=os.environ.get("RUN_TOPIC", "defense"))
    args = ap.parse_args()
    load_env()
    trigger = os.environ.get("RUN_TRIGGER", "local")
    print(json.dumps(run_ingest(args.topic, args.sources or None, trigger=trigger), ensure_ascii=False, indent=2))
