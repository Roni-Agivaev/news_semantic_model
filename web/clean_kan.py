"""
One-off: strip Kan's sign-in prompt and footer from articles stored before the
scraper learned to (lib/scraper.strip_boilerplate). Both topics' tables.

    python clean_kan.py --dry-run   # count the affected rows, change nothing
    python clean_kan.py

Needs DATABASE_URL, read from web/.env if present.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_csv import load_env  # noqa: E402
from lib import db  # noqa: E402
from lib.scraper import _FOOTER_MARKER, _SIGN_IN_PROMPT, strip_boilerplate  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()
    conn = db.connect()
    try:
        for topic, table in db.TABLES.items():
            rows = conn.execute(
                f"SELECT id, content FROM {table} WHERE content LIKE %s OR content LIKE %s",
                (f"%{_SIGN_IN_PROMPT}%", f"%{_FOOTER_MARKER}%"),
            ).fetchall()
            print(f"{topic}: {len(rows)} article(s) with Kan boilerplate")
            if args.dry_run or not rows:
                continue
            with conn.cursor() as cur:
                cur.executemany(f"UPDATE {table} SET content = %s WHERE id = %s",
                                [(strip_boilerplate(r["content"]), r["id"]) for r in rows])
            conn.commit()
            print(f"{topic}: cleaned")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
