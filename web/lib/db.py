"""
Postgres (Supabase) access. The schema is created on first use, so there is no
separate migration step.

Use Supabase's *transaction pooler* connection string (port 6543) for Vercel;
prepared statements are disabled because that pooler doesn't support them.
"""
import os

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           BIGSERIAL PRIMARY KEY,
    source       TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    content      TEXT,
    published_at TIMESTAMPTZ,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    origin       TEXT NOT NULL DEFAULT 'scraper',  -- 'scraper' or 'csv'
    score        REAL                              -- morale score, filled in later
);
CREATE UNIQUE INDEX IF NOT EXISTS articles_source_title ON articles (source, title);
CREATE INDEX IF NOT EXISTS articles_published_at ON articles (published_at);
CREATE INDEX IF NOT EXISTS articles_ingested_at ON articles (ingested_at);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id           BIGSERIAL PRIMARY KEY,
    ran_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL,
    links_found  INTEGER NOT NULL DEFAULT 0,
    new_articles INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS ingest_runs_source_ran_at ON ingest_runs (source, ran_at DESC);
-- articles saved with title/date only because the page itself was blocked
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS title_only INTEGER NOT NULL DEFAULT 0;

-- Supabase exposes the public schema over its REST API; RLS with no policies
-- blocks that path. Our direct Postgres connection is unaffected.
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest_runs ENABLE ROW LEVEL SECURITY;
"""

_schema_ready = False


def connect():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)
    ensure_schema(conn)
    return conn


def ensure_schema(conn):
    global _schema_ready
    if not _schema_ready:
        conn.execute(SCHEMA)
        conn.commit()
        _schema_ready = True


def existing_urls(conn, urls):
    """URLs already stored with their text. Title-only rows are left out so a
    later run (e.g. from a machine the site doesn't block) can fill them in."""
    if not urls:
        return set()
    rows = conn.execute(
        "SELECT url FROM articles WHERE url = ANY(%s) AND COALESCE(content, '') <> ''", (list(urls),)
    ).fetchall()
    return {r["url"] for r in rows}


def insert_articles(conn, articles, origin="scraper"):
    """Insert articles, skipping any whose url or (source, title) already exists.
    An article with text also fills in a stored title-only row with the same url.
    Returns the number of new rows."""
    inserted = 0
    with conn.cursor() as cur:
        for a in articles:
            content = (a.get("content") or "").replace("\x00", "")
            if content:
                cur.execute(
                    """UPDATE articles SET content = %s
                       WHERE (url = %s OR (source = %s AND title = %s)) AND COALESCE(content, '') = ''""",
                    (content, a["url"], a["source"], a["title"]),
                )
                if cur.rowcount:
                    continue
            cur.execute(
                """
                INSERT INTO articles (source, url, title, content, published_at, ingested_at, origin, score)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), %s, %s)
                ON CONFLICT DO NOTHING
                """,
                # Postgres rejects NUL characters in text, which scraped pages occasionally contain
                (a["source"], a["url"], a["title"].replace("\x00", ""), content, a.get("published_at"),
                 a.get("ingested_at"), origin, a.get("score")),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def log_run(conn, source, links_found, new_articles, failed, title_only=0, error=None):
    conn.execute(
        """INSERT INTO ingest_runs (source, links_found, new_articles, failed, title_only, error)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (source, links_found, new_articles, failed, title_only, error),
    )
    conn.commit()


def stats(conn, by="ingested", days=30):
    """Counts for the dashboard. `by` picks which date articles are grouped on;
    days=0 means all time."""
    date_col = "COALESCE(published_at, ingested_at)" if by == "published" else "ingested_at"
    # Days are counted in Israel time. Overridable for Postgres builds without tz data.
    tz = os.environ.get("DASHBOARD_TZ", "Asia/Jerusalem")
    day_expr = f"({date_col} AT TIME ZONE %(tz)s)::date"

    totals = conn.execute(
        "SELECT source, count(*)::int AS count FROM articles GROUP BY source ORDER BY count DESC"
    ).fetchall()

    daily = conn.execute(
        f"""
        SELECT {day_expr} AS day, source, count(*)::int AS count
        FROM articles
        WHERE %(days)s::int = 0 OR {day_expr} >= (now() AT TIME ZONE %(tz)s)::date - %(days)s::int
        GROUP BY 1, 2
        ORDER BY 1 DESC, 2
        """,
        {"tz": tz, "days": days},
    ).fetchall()

    last_runs = conn.execute(
        """
        SELECT DISTINCT ON (source) source, ran_at, links_found, new_articles, failed, title_only, error
        FROM ingest_runs
        ORDER BY source, ran_at DESC
        """
    ).fetchall()

    return {
        "by": by,
        "days": days,
        "total": sum(r["count"] for r in totals),
        "totals": totals,
        "daily": [{**r, "day": r["day"].isoformat()} for r in daily],
        "last_runs": [{**r, "ran_at": r["ran_at"].isoformat()} for r in last_runs],
    }
