"""
One ingestion run: for every site, collect the category page links, skip the
ones already in the database, scrape the rest and insert them.

Each run is narrated step by step to the ingest_events table (lib/events.py),
which the /logs page reads.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from . import db
from .events import DbWriter, RunLog, null_log
from .scraper import MAX_PAGES, SITES, get_links, get_sitemap_entries, scrape_article

ARTICLE_WORKERS = 4  # parallel article fetches per site


def _err(where, e):
    return f"{where}: {type(e).__name__}: {e}"[:250]


def ingest_site(source, max_pages=MAX_PAGES, stop_at_known=True, log=null_log, run_id=None):
    """Scrape one site. Opens its own connection so sites can run in parallel.

    `stop_at_known` lets the walk end as soon as a section page holds nothing
    new, which is what the daily cron wants. backfill.py turns it off so a deep
    walk reaches old articles even when the recent pages are fully stored.

    `log` receives the site's events (see lib/events.py); `run_id` ties the
    summary row in ingest_runs to them."""
    result = {"source": source, "links_found": 0, "new_articles": 0, "failed": 0, "title_only": 0, "error": None}
    started = time.monotonic()
    conn = db.connect()
    try:
        log("info", "start", f"Started: up to {max_pages} section page(s)"
            + ("" if stop_at_known else ", deep walk"))
        errors = []
        # Sites with a news sitemap: it lists new articles with title and date,
        # and still works when the site blocks its category page.
        sitemap = {}
        if SITES[source].get("sitemap_url"):
            try:
                sitemap = get_sitemap_entries(source)
                log("info", "sitemap", f"Sitemap lists {len(sitemap)} articles", url=SITES[source]["sitemap_url"])
            except Exception as e:
                errors.append(_err("sitemap", e))
                log("warn", "sitemap", f"Sitemap failed: {type(e).__name__}: {e}", url=SITES[source]["sitemap_url"])
        try:
            links = get_links(
                source,
                known=(lambda urls: db.existing_urls(conn, urls)) if stop_at_known else None,
                max_pages=max_pages,
                log=log,
            )
        except Exception as e:
            links = []
            level = "warn" if sitemap else "error"
            log(level, "section", f"Section page failed: {type(e).__name__}: {e}",
                url=SITES[source]["category_url"])
            if not sitemap:
                errors.append(_err("category page", e))
        links += [u for u in sitemap if u not in links]

        if not links:
            result["error"] = "; ".join(errors) or "no article links found"
            return result

        result["links_found"] = len(links)
        known = db.existing_urls(conn, links)
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
        result["title_only"] = sum(1 for a in articles if not a["content"])
        result["new_articles"] = db.insert_articles(conn, articles)
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
            db.log_run(conn, run_id=run_id, **result)
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


def run_ingest(sources=None, max_pages=MAX_PAGES, stop_at_known=True, trigger="manual"):
    """Scrape the given sites in parallel. `trigger` names who started the run
    (cron, manual, kan-action, backfill, local) on the /logs page."""
    sources = sources or list(SITES)
    # Make sure the schema exists once before the parallel workers race to create it.
    db.connect().close()
    run_log = RunLog(trigger, sources, writer=DbWriter(db.connect))
    run_log.start()
    results = []
    try:
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            results = list(pool.map(
                lambda s: ingest_site(s, max_pages, stop_at_known, log=run_log.for_site(s), run_id=run_log.run_id),
                sources))
    finally:
        run_log.finish(
            new_articles=sum(r["new_articles"] for r in results),
            summary={r["source"]: {k: v for k, v in r.items() if k != "source"} for r in results} or None,
        )
    return {"run_id": run_log.run_id, "new_articles": sum(r["new_articles"] for r in results), "sites": results}
