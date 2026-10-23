"""
One-time import of existing article CSVs into the database. Run locally:

    python import_csv.py path\\to\\log_csv.csv --dry-run     # preview only
    python import_csv.py path\\to\\log_csv.csv               # import
    python import_csv.py Ynet_news.csv --source Ynet        # CSV without a Source column

Understands both CSV layouts in this project:
  - pipeline log:   Time, Source, Title, Content, Predicted Score, Exact Input
  - bulk scrapers:  Date, Title, Author, Content, URL (+ scores) - site taken from the URL

Rows already in the database (same URL, or same source + title) are skipped,
so running it twice is safe. Needs DATABASE_URL (read from web/.env if present).
"""
import argparse
import csv
import hashlib
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import db  # noqa: E402
from lib.scraper import SITES, parse_date  # noqa: E402

# Old names used in earlier CSVs -> the names the scrapers use now (see pipeline/fixes.py)
SOURCE_ALIASES = {
    "ynet": "Ynet",
    "kan": "Kan News", "kan news": "Kan News", "kannews": "Kan News",
    "13tv": "Channel 13", "channel 13": "Channel 13", "reshet13": "Channel 13", "reshet 13": "Channel 13",
    "14": "Channel 14", "channel 14": "Channel 14", "now14": "Channel 14", "c14": "Channel 14",
    "i24": "I24 NEWS", "i24news": "I24 NEWS", "i24 news": "I24 NEWS",
    "mako": "Channel 12", "channel 12": "Channel 12", "keshet12": "Channel 12", "n12": "Channel 12",
}

COLUMN_ALIASES = {
    "source": ["source", "site", "website"],
    "title": ["title", "headline"],
    "content": ["content", "text", "body"],
    "url": ["url", "link"],
    "published_at": ["date", "published", "published_at", "datepublished"],
    "ingested_at": ["time", "ingested_at", "scraped_at"],
    "score": ["predicted score", "content_score", "score"],
}


def load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def normalize_source(value):
    v = (value or "").strip()
    return SOURCE_ALIASES.get(v.lower(), v)


def source_from_url(url):
    """Match a URL to a site by its domain, e.g. https://www.mako.co.il/... -> Channel 12."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for name, site in SITES.items():
        if host and host == urlparse(site["base"]).netloc.lower().removeprefix("www."):
            return name
    return None


def read_rows(path, forced_source=None):
    # Rows without their own ingest time are dated by when the CSV was last saved,
    # so old articles don't all show up on the dashboard as "ingested today".
    file_saved_at = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        cols = {key: next((header[a] for a in aliases if a in header), None) for key, aliases in COLUMN_ALIASES.items()}
        if not cols["title"]:
            sys.exit(f"{path}: no Title column found (columns: {reader.fieldnames})")
        if not cols["source"] and not cols["url"] and not forced_source:
            sys.exit(f"{path}: no Source or URL column - pass --source, one of: {', '.join(SITES)}")

        for raw in reader:
            get = lambda key: (raw.get(cols[key]) or "").strip() if cols[key] else ""
            title = get("title")
            if not title:
                continue
            url = get("url")
            source = normalize_source(forced_source or get("source")) or source_from_url(url)
            if not source:
                print(f"  skipped (unknown site): {url or title[:60]}")
                continue
            if not url:
                # The old pipeline log has no URL column; give the row a stable synthetic key.
                url = "csv:" + hashlib.sha1(f"{source}|{title}".encode("utf-8")).hexdigest()
            try:
                score = float(get("score")) if get("score") else None
            except ValueError:
                score = None
            yield {
                "source": source,
                "url": url,
                "title": title,
                "content": get("content"),
                "published_at": parse_date(get("published_at")),
                "ingested_at": parse_date(get("ingested_at").replace(" ", "T", 1)) or file_saved_at,
                "score": score,
            }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_files", nargs="+")
    ap.add_argument("--source", help="Source name for every row, for CSVs without a Source column")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be imported, write nothing")
    args = ap.parse_args()
    load_env()

    rows = [r for path in args.csv_files for r in read_rows(path, args.source)]
    by_source = Counter(r["source"] for r in rows)
    print(f"Read {len(rows)} rows:")
    for s, n in by_source.most_common():
        flag = "" if s in SITES else "   <- not one of the scraper's site names"
        print(f"  {s:<12} {n}{flag}")
    print(f"  with published date: {sum(1 for r in rows if r['published_at'])}")

    if args.dry_run:
        print("Dry run - nothing written.")
        return

    conn = db.connect()
    try:
        inserted = db.insert_articles(conn, rows, origin="csv")
    finally:
        conn.close()
    print(f"Inserted {inserted} new articles ({len(rows) - inserted} were already in the database).")


if __name__ == "__main__":
    main()
