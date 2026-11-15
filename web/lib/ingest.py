"""
One ingestion run for one topic (defense or politics): for every source,
collect the section links, skip the ones already in the topic's table, scrape
the rest and insert them.

Each run is narrated step by step to the ingest_events table (lib/events.py),
which the /logs page reads.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg

from . import db
from .events import DbWriter, RunLog, null_log
from .scraper import MAX_PAGES, SITES, get_links, get_sitemap_entries, scrape_article, sources as topic_sources

ARTICLE_WORKERS = 4  # parallel article fetches per site


class _Conn:
    """A database connection that is reopened once when the server has dropped it.

    A source can scrape for minutes between two database calls, and the server
    may close connections meanwhile (2026-11-15: every connection of a politics
    backfill was dropped at once and five sources lost their articles)."""

    def __init__(self):
        self.conn = db.connect()

    def run(self, fn, *args, **kwargs):
        try:
            return fn(self.conn, *args, **kwargs)
        except psycopg.OperationalError:
            self.close()
            self.conn = db.connect()
            return fn(self.conn, *args, **kwargs)

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


def _err(where, e):
    return f"{where}: {type(e).__name__}: {e}"[:250]


def ingest_site(topic, source, max_pages=MAX_PAGES, stop_at_known=True, log=null_log, run_id=None, since=None):
    """Scrape one source for one topic. Opens its own connection so sources can
    run in parallel.

    `stop_at_known` lets the walk end as soon as a section page holds nothing
    new, which is what the daily cron wants. backfill.py turns it off so a deep
    walk reaches old articles even when the recent pages are fully stored.

    `since` (an aware datetime) drops scraped articles published before it;
    backfill.py uses it to keep a deep walk to its date window.

    `log` receives the site's events (see lib/events.py); `run_id` ties the
    summary row in ingest_runs to them."""
    site = SITES[topic][source]
    result = {"source": source, "links_found": 0, "new_articles": 0, "failed": 0, "title_only": 0, "error": None}
    started = time.monotonic()
    conn = _Conn()
    try:
        log("info", "start", f"Started: up to {max_pages} section page(s)"
            + ("" if stop_at_known else ", deep walk"))
        errors = []
        # Sources with a news sitemap: it lists new articles with title and date,
        # and still works when the site blocks its section pages.
        sitemap = {}
        if site.get("sitemap_url"):
            try:
                sitemap = get_sitemap_entries(topic, source)
                log("info", "sitemap", f"Sitemap lists {len(sitemap)} articles", url=site["sitemap_url"])
            except Exception as e:
                errors.append(_err("sitemap", e))
                log("warn", "sitemap", f"Sitemap failed: {type(e).__name__}: {e}", url=site["sitemap_url"])
        try:
            tagged = get_links(
                topic, source,
                known=(lambda urls: conn.run(db.existing_urls, urls, topic=topic)) if stop_at_known else None,
                max_pages=max_pages,
                log=log,
            )
        except Exception as e:
            tagged = []
            level = "warn" if sitemap else "error"
            log(level, "section", f"Section page failed: {type(e).__name__}: {e}",
                url=site["sections"][0].get("rss_url") or site["sections"][0]["category_url"])
            if not sitemap:
                errors.append(_err("category page", e))
        section_of = dict(tagged)
        for url, entry in sitemap.items():
            section_of.setdefault(url, entry["section"])
        links = list(section_of)

        if not links:
            result["error"] = "; ".join(errors) or "no article links found"
            return result

        result["links_found"] = len(links)
        known = conn.run(db.existing_urls, links, topic=topic)
        todo = [u for u in links if u not in known]
        log("info", "links", f"{len(links)} links: {len(known)} already stored, {len(todo)} to scrape")

        def scrape(url):
            try:
                return scrape_article(source, url, fallback=sitemap.get(url), log=log)
            except Exception as e:
                log("error", "article", f"Failed: {type(e).__name__}: {e}", url=url)
                return None

        with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
            scraped = list(pool.map(scrape, todo))

        articles = [a for a in scraped if a]
        result["failed"] = len(todo) - len(articles)
        for a in articles:
            a["section"] = section_of.get(a["url"])
        if since is not None:
            kept = [a for a in articles if not a.get("published_at") or a["published_at"] >= since]
            if len(kept) < len(articles):
                log("info", "save", f"Skipped {len(articles) - len(kept)} published before {since:%Y-%m-%d}")
            articles = kept
        result["title_only"] = sum(1 for a in articles if not a["content"])
        result["new_articles"] = conn.run(db.insert_articles, articles, topic=topic)
        if articles:
            dupes = len(articles) - result["new_articles"]
            log("info", "save", f"Saved {result['new_articles']} new article(s)"
                + (f"; {dupes} matched a stored article or filled in its text" if dupes else ""))
        return result
    except Exception as e:
        result["error"] = _err("ingest", e)
        raise
    finally:
        _log_summary(log, result, time.monotonic() - started)
        try:
            conn.run(db.log_run, run_id=run_id, topic=topic, **result)
        finally:
            conn.close()


def _log_summary(log, r, seconds):
    if r["error"]:
        log("error", "done", f"Failed after {seconds:.0f}s: {r['error']}")
        return
    level = "warn" if r["failed"] or r["title_only"] else "info"
    parts = [f"{r['new_articles']} new", f"{r['failed']} failed"]
    if r["title_only"]:
        parts.append(f"{r['title_only']} title only")
    log(level, "done", f"Done in {seconds:.0f}s: " + ", ".join(parts))


def run_ingest(topic, sources=None, max_pages=MAX_PAGES, stop_at_known=True, trigger="manual", since=None):
    """Scrape the given sources of one topic in parallel. `trigger` names who
    started the run (cron, manual, kan-action, backfill, local) on the /logs page."""
    known_sources = topic_sources(topic)  # raises ValueError for an unknown topic
    sources = list(sources or known_sources)
    unknown = [s for s in sources if s not in known_sources]
    if unknown:
        raise ValueError(f"unknown {topic} source(s): {', '.join(unknown)}")
    # Make sure the schema exists once before the parallel workers race to create it.
    db.connect().close()
    run_log = RunLog(trigger, sources, writer=DbWriter(db.connect), topic=topic)
    run_log.start()
    results = []
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            results = list(pool.map(
                lambda s: ingest_site(topic, s, max_pages, stop_at_known, log=run_log.for_site(s),
                                      run_id=run_log.run_id, since=since),
                sources))
    finally:
        run_log.finish(
            new_articles=sum(r["new_articles"] for r in results),
            summary={r["source"]: {k: v for k, v in r.items() if k != "source"} for r in results} or None,
        )
    return {"run_id": run_log.run_id, "topic": topic,
            "new_articles": sum(r["new_articles"] for r in results), "sites": results}
