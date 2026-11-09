"""
Postgres (Supabase) access. The schema is created on first use, so there is no
separate migration step.

Use Supabase's *transaction pooler* connection string (port 6543) for Vercel;
prepared statements are disabled because that pooler doesn't support them.
"""
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .health import site_status

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

-- the scrape run (scrape_runs.id) each per-site summary belongs to
ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS run_id TEXT;

-- One row per scrape run (all sites together), and its step-by-step events,
-- written by lib/events.py and shown on the /logs page. Kept for EVENT_DAYS.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id           TEXT PRIMARY KEY,
    trigger      TEXT NOT NULL,
    sources      TEXT[] NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',   -- running / ok / warn / error
    new_articles INTEGER,
    summary      JSONB
);
CREATE INDEX IF NOT EXISTS scrape_runs_started_at ON scrape_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS ingest_events (
    id      BIGSERIAL PRIMARY KEY,
    run_id  TEXT NOT NULL,
    at      TIMESTAMPTZ NOT NULL,
    source  TEXT,
    level   TEXT NOT NULL,     -- info / warn / error
    step    TEXT NOT NULL,
    message TEXT NOT NULL,
    url     TEXT,
    detail  JSONB
);
CREATE INDEX IF NOT EXISTS ingest_events_run ON ingest_events (run_id, at, id);
CREATE INDEX IF NOT EXISTS ingest_events_at ON ingest_events (at);

-- Supabase exposes the public schema over its REST API; RLS with no policies
-- blocks that path. Our direct Postgres connection is unaffected.
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest_events ENABLE ROW LEVEL SECURITY;
"""

_schema_ready = False


def connect():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    conn = psycopg.connect(url, row_factory=dict_row, prepare_threshold=None, connect_timeout=15)
    ensure_schema(conn)
    return conn


# True when the tables, the newest columns and row-level security are all in place.
# A plain catalog read: it takes no table locks.
SCHEMA_CHECK = """
SELECT (SELECT count(*) FROM pg_class
        WHERE oid IN (to_regclass('public.articles'), to_regclass('public.ingest_runs'),
                      to_regclass('public.scrape_runs'), to_regclass('public.ingest_events'))
          AND relrowsecurity) = 4
   AND (SELECT count(*) FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'ingest_runs'
          AND column_name IN ('title_only', 'run_id')) = 2 AS ready
"""

EVENT_DAYS = 30            # how long run logs are kept
UNFINISHED_AFTER_MIN = 15  # a run silent this long without finishing was cut off


def ensure_schema(conn):
    """Create the schema if it is missing. Runs the DDL only when needed: its
    ALTER TABLE takes an exclusive lock, and two connections doing that at once
    (two API functions starting together) deadlock."""
    global _schema_ready
    if _schema_ready:
        return
    ready = conn.execute(SCHEMA_CHECK).fetchone()["ready"]
    if not ready:
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


def log_run(conn, source, links_found, new_articles, failed, title_only=0, error=None, run_id=None):
    conn.execute(
        """INSERT INTO ingest_runs (source, links_found, new_articles, failed, title_only, error, run_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (source, links_found, new_articles, failed, title_only, error, run_id),
    )
    conn.commit()


# ---------- run logs (lib/events.py writes, /api/logs reads) ----------

def start_scrape_run(conn, run_id, trigger, sources):
    conn.execute("INSERT INTO scrape_runs (id, trigger, sources) VALUES (%s, %s, %s)",
                 (run_id, trigger, list(sources)))
    conn.commit()


def add_events(conn, events):
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO ingest_events (run_id, at, source, level, step, message, url, detail)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(e["run_id"], e["at"], e["source"], e["level"], e["step"], e["message"].replace("\x00", ""),
              e["url"], Jsonb(e["detail"]) if e["detail"] else None) for e in events],
        )
    conn.commit()


def finish_scrape_run(conn, run_id, status, new_articles, summary):
    conn.execute(
        """UPDATE scrape_runs SET finished_at = now(), status = %s, new_articles = %s, summary = %s
           WHERE id = %s""",
        (status, new_articles, Jsonb(summary) if summary else None, run_id),
    )
    # Housekeeping: old logs go, so the tables stay small
    conn.execute("DELETE FROM ingest_events WHERE at < now() - make_interval(days => %s)", (EVENT_DAYS,))
    conn.execute("DELETE FROM scrape_runs WHERE started_at < now() - make_interval(days => %s)", (EVENT_DAYS,))
    conn.commit()


# A run that never reported back (function timed out, runner killed) and has
# been silent for UNFINISHED_AFTER_MIN shows as 'unfinished' instead of 'running'.
_RUN_COLUMNS = """
    r.id, r.trigger, r.sources, r.started_at, r.finished_at, r.new_articles, r.summary,
    CASE WHEN r.finished_at IS NULL
              AND greatest(r.started_at, e.last_at) < now() - make_interval(mins => %(stale)s)
         THEN 'unfinished' ELSE r.status END AS status,
    coalesce(e.info, 0) AS info, coalesce(e.warn, 0) AS warn, coalesce(e.error, 0) AS error,
    e.last_at,
    extract(epoch FROM coalesce(r.finished_at, greatest(r.started_at, e.last_at)) - r.started_at)::float AS seconds
"""
_RUN_EVENTS = """
    LEFT JOIN LATERAL (
        SELECT count(*) FILTER (WHERE level = 'info')  AS info,
               count(*) FILTER (WHERE level = 'warn')  AS warn,
               count(*) FILTER (WHERE level = 'error') AS error,
               max(at) AS last_at
        FROM ingest_events WHERE run_id = r.id) e ON true
"""


def list_scrape_runs(conn, limit=60):
    rows = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM scrape_runs r {_RUN_EVENTS} ORDER BY r.started_at DESC LIMIT %(limit)s",
        {"stale": UNFINISHED_AFTER_MIN, "limit": limit},
    ).fetchall()
    conn.commit()
    return rows


def get_scrape_run(conn, run_id, max_events=5000):
    """The run and its events, oldest first. None if there is no such run."""
    run = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM scrape_runs r {_RUN_EVENTS} WHERE r.id = %(id)s",
        {"stale": UNFINISHED_AFTER_MIN, "id": run_id},
    ).fetchone()
    events = []
    if run:
        events = conn.execute(
            """SELECT id, at, source, level, step, message, url, detail
               FROM ingest_events WHERE run_id = %s ORDER BY at, id LIMIT %s""",
            (run_id, max_events),
        ).fetchall()
    conn.commit()
    return {"run": run, "events": events} if run else None


def stats(conn, by="ingested", days=30, coverage_days=90):
    """Counts for the dashboard. `by` picks which date articles are grouped on;
    days=0 means all time."""
    date_col = "COALESCE(published_at, ingested_at)" if by == "published" else "ingested_at"
    # Days are counted in Israel time. Overridable for Postgres builds without tz data.
    tz = os.environ.get("DASHBOARD_TZ", "Asia/Jerusalem")
    day_expr = f"({date_col} AT TIME ZONE %(tz)s)::date"

    # Everything in one round trip: the database is far away, so each query costs ~0.25s.
    row = conn.execute(
        f"""
        WITH runs AS (
            SELECT *, (error IS NULL AND links_found > 0) AS ok,
                   row_number() OVER (PARTITION BY source ORDER BY ran_at DESC) AS rn
            FROM ingest_runs
        )
        SELECT json_build_object(
          'today', (now() AT TIME ZONE %(tz)s)::date,

          'kpis', (SELECT json_build_object(
              'total',     count(*),
              'from_csv',  count(*) FILTER (WHERE origin = 'csv'),
              'today',     count(*) FILTER (WHERE (ingested_at AT TIME ZONE %(tz)s)::date = (now() AT TIME ZONE %(tz)s)::date),
              'with_text', count(*) FILTER (WHERE coalesce(content, '') <> ''),
              'with_date', count(*) FILTER (WHERE published_at IS NOT NULL),
              'scored',    count(*) FILTER (WHERE score IS NOT NULL),
              'oldest',    (min(published_at) AT TIME ZONE %(tz)s)::date,
              'last7',     count(*) FILTER (WHERE ingested_at >= now() - interval '7 days'),
              'prev7',     count(*) FILTER (WHERE ingested_at >= now() - interval '14 days'
                                              AND ingested_at <  now() - interval '7 days'))
            FROM articles),

          'daily', (SELECT coalesce(json_agg(d ORDER BY d.day DESC, d.source), '[]') FROM (
              SELECT {day_expr} AS day, source, count(*)::int AS count
              FROM articles
              WHERE %(days)s::int = 0 OR {day_expr} >= (now() AT TIME ZONE %(tz)s)::date - %(days)s::int
              GROUP BY 1, 2) d),

          -- Per site: size and data quality
          'sites', (SELECT coalesce(json_agg(s ORDER BY s.total DESC), '[]') FROM (
              SELECT source,
                     count(*)::int AS total,
                     count(*) FILTER (WHERE origin = 'csv')::int AS from_csv,
                     count(*) FILTER (WHERE coalesce(content, '') <> '')::int AS with_text,
                     count(*) FILTER (WHERE published_at IS NOT NULL)::int AS with_date,
                     round(avg(length(content)) FILTER (WHERE coalesce(content, '') <> ''))::int AS avg_len,
                     count(*) FILTER (WHERE score IS NOT NULL)::int AS scored,
                     (min(published_at) AT TIME ZONE %(tz)s)::date AS oldest,
                     (max(published_at) AT TIME ZONE %(tz)s)::date AS newest,
                     max(ingested_at) AS last_ingested,
                     count(*) FILTER (WHERE ingested_at >= now() - interval '7 days')::int AS last7,
                     round((percentile_cont(0.5) WITHIN GROUP (
                         ORDER BY extract(epoch FROM ingested_at - published_at) / 3600)
                       -- daily catch-up only: backfilled history (stored long after publication) would swamp it
                       FILTER (WHERE origin = 'scraper' AND published_at IS NOT NULL
                                 AND ingested_at - published_at < interval '30 days'))::numeric, 1) AS median_delay_h
              FROM articles GROUP BY source) s),

          -- Per site: scraping health
          'health', (SELECT coalesce(json_agg(h), '[]') FROM (
              SELECT r.source,
                     max(r.ran_at) FILTER (WHERE r.ok) AS last_ok,
                     (SELECT row_to_json(x) FROM (
                         SELECT ran_at, ok, links_found, new_articles, failed, title_only, error
                         FROM runs WHERE source = r.source AND rn = 1) x) AS last_run,
                     (SELECT json_agg(json_build_object('ran_at', ran_at, 'ok', ok, 'new', new_articles,
                                                        'links', links_found, 'failed', failed,
                                                        'error', error) ORDER BY ran_at)
                      FROM runs WHERE source = r.source AND rn <= 14) AS history
              FROM runs r GROUP BY r.source) h),

          -- Every site's recent runs in one log, newest first
          'runs', (SELECT coalesce(json_agg(r ORDER BY r.ran_at DESC), '[]') FROM (
              SELECT ran_at, source, ok, links_found, new_articles, failed, title_only, error, run_id
              FROM runs ORDER BY ran_at DESC LIMIT 80) r),

          -- Articles per site per publish day, for the coverage heatmap
          'coverage', (SELECT coalesce(json_agg(c), '[]') FROM (
              SELECT (published_at AT TIME ZONE %(tz)s)::date AS day, source, count(*)::int AS count
              FROM articles
              WHERE published_at >= (now() AT TIME ZONE %(tz)s)::date - %(cov)s::int
              GROUP BY 1, 2) c),

          'latest', (SELECT coalesce(json_agg(a), '[]') FROM (
              SELECT source, title, url, published_at, ingested_at
              FROM articles WHERE origin = 'scraper'
              ORDER BY coalesce(published_at, ingested_at) DESC LIMIT 12) a)
        ) AS stats
        """,
        {"tz": tz, "days": days, "cov": coverage_days},
    ).fetchone()
    out = {"by": by, "days": days, "coverage_days": coverage_days, **row["stats"]}
    now = datetime.now(timezone.utc)
    for h in out["health"]:
        h["status"] = site_status(h["last_ok"], h["history"] or [], now)
    return out


def search_articles(conn, q="", source="", date_from=None, date_to=None, limit=50, offset=0):
    """One page of articles for the dashboard's explorer, newest first.
    `q` matches the title or the text; dates bound the publish date (inclusive)."""
    # ILIKE treats % and _ as wildcards and \ as the escape; the search box should not
    pattern = "%" + q.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_") + "%"
    rows = conn.execute(
        """
        SELECT source, title, url, published_at, ingested_at, origin, score,
               length(content) AS length, left(content, 700) AS snippet,
               count(*) OVER () AS total
        FROM articles
        WHERE (%(q)s = '' OR title ILIKE %(pat)s OR content ILIKE %(pat)s)
          AND (%(source)s = '' OR source = %(source)s)
          AND (%(from)s::date IS NULL OR published_at >= %(from)s::date)
          AND (%(to)s::date IS NULL OR published_at < %(to)s::date + 1)
        ORDER BY coalesce(published_at, ingested_at) DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        {"q": q, "pat": pattern, "source": source, "from": date_from, "to": date_to,
         "limit": limit, "offset": offset},
    ).fetchall()
    total = rows[0]["total"] if rows else 0
    for r in rows:
        del r["total"]
    return {"total": total, "limit": limit, "offset": offset, "items": rows}
