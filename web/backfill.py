"""
One-time deep walk of one topic's sections, to collect articles from before the
daily scraper started reading them. Run locally - it takes far longer than
Vercel's 300 s function ceiling.

    python backfill.py --dry-run                         # show the plan, write nothing
    python backfill.py                                   # defense, every source
    python backfill.py --topic politics                  # politics, every source
    python backfill.py --topic defense Maariv JDN        # named sources only
    python backfill.py --days 30 --max-pages 10

Articles published more than --days ago (default 90; 0 = no limit) are not
stored. Section pages carry no dates, so the walk itself is bounded by
--max-pages; sections without a `page_url` read their one page however deep
the cap.

Unlike the daily cron this does not stop when a page is fully stored: the
recent pages are, and the gap is behind them. Articles already in the database
are still skipped, so running it twice is safe. Needs DATABASE_URL, read from
web/.env if present.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.scraper import SITES, TOPICS, sources as topic_sources  # noqa: E402

BACKFILL_PAGES = 25
BACKFILL_DAYS = 90


def build_args(argv, now=None):
    """Parse the command line. Returns (topic, sources, max_pages, since, dry_run)."""
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="source names; default all of the topic's")
    ap.add_argument("--topic", choices=TOPICS, default="defense")
    ap.add_argument("--max-pages", type=int, default=BACKFILL_PAGES,
                    help=f"section pages to walk per section (default {BACKFILL_PAGES})")
    ap.add_argument("--days", type=int, default=BACKFILL_DAYS,
                    help=f"keep articles published in the last N days (default {BACKFILL_DAYS}; 0 = all)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be walked and exit")
    args = ap.parse_args(argv)

    known = topic_sources(args.topic)
    sources = args.sources or known
    unknown = [s for s in sources if s not in known]
    if unknown:
        ap.error(f"unknown {args.topic} source(s): {', '.join(unknown)}. Known: {', '.join(known)}")
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=args.days) if args.days > 0 else None
    return args.topic, sources, args.max_pages, since, args.dry_run


def main():
    topic, sources, max_pages, since, dry_run = build_args(sys.argv[1:])
    for s in sources:
        for section in SITES[topic][s]["sections"]:
            pages = 1 if section.get("rss_url") or not section.get("page_url") else max_pages
            print(f"{topic} / {s} / {section['name']}: {pages} page(s)")
    print(f"keeping articles published since {since:%Y-%m-%d}" if since else "keeping every date")
    if dry_run:
        print("dry run: nothing written")
        return

    from import_csv import load_env
    from lib.ingest import run_ingest
    load_env()
    print(f"walking {len(sources)} source(s), up to {max_pages} pages per section; "
          f"this takes many minutes", flush=True)
    print(json.dumps(run_ingest(topic, sources, max_pages=max_pages, stop_at_known=False,
                                trigger="backfill", since=since),
                     ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
