"""
One-time deep walk of every site's section, to collect the articles that were
never ingested because the scraper only read page 1. Run locally - it takes
far longer than Vercel's 300 s function ceiling.

    python backfill.py --dry-run             # show the plan, write nothing
    python backfill.py                       # all sites, 25 pages each
    python backfill.py "Channel 13" "I24 NEWS"
    python backfill.py --max-pages 10

25 pages reaches roughly 4-5 months back, at the measured 5-6 days per page.
Sites without a `page_url` (Ynet, Channel 14, Kan News) read one page however
deep the cap, because their sections do not paginate.

Unlike the daily cron this does not stop when a page is fully stored: the
recent pages are, and the gap is behind them. Articles already in the database
are still skipped, so running it twice is safe. Needs DATABASE_URL, read from
web/.env if present.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_csv import load_env  # noqa: E402
from lib.ingest import run_ingest  # noqa: E402
from lib.scraper import SITES  # noqa: E402

BACKFILL_PAGES = 25


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="site names; default all of them")
    ap.add_argument("--max-pages", type=int, default=BACKFILL_PAGES,
                    help=f"section pages to walk per site (default {BACKFILL_PAGES})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be walked and exit")
    args = ap.parse_args()

    sources = args.sources or list(SITES)
    unknown = [s for s in sources if s not in SITES]
    if unknown:
        ap.error(f"unknown site(s): {', '.join(unknown)}. Known: {', '.join(SITES)}")

    for s in sources:
        pages = args.max_pages if SITES[s].get("page_url") else 1
        print(f"{s}: {pages} page(s)")
    if args.dry_run:
        print("dry run: nothing written")
        return

    load_env()
    print(f"walking {len(sources)} site(s), up to {args.max_pages} pages each; "
          f"this takes many minutes", flush=True)
    print(json.dumps(run_ingest(sources, max_pages=args.max_pages, stop_at_known=False),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
