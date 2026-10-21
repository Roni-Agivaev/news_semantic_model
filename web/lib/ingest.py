"""
One ingestion run: for every site, collect the category page links, skip the
ones already in the database, scrape the rest and insert them.
"""
from concurrent.futures import ThreadPoolExecutor

from . import db
from .scraper import SITES, get_links, scrape_article

ARTICLE_WORKERS = 4  # parallel article fetches per site


def ingest_site(source):
    """Scrape one site. Opens its own connection so sites can run in parallel."""
    result = {"source": source, "links_found": 0, "new_articles": 0, "failed": 0, "error": None}
    conn = db.connect()
    try:
        try:
            links = get_links(source)
        except Exception as e:
            result["error"] = f"category page: {type(e).__name__}: {e}"[:500]
            return result

        result["links_found"] = len(links)
        known = db.existing_urls(conn, links)
        todo = [u for u in links if u not in known]

        def scrape(url):
            try:
                return scrape_article(source, url)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
            scraped = list(pool.map(scrape, todo))

        articles = [a for a in scraped if a]
        result["failed"] = len(todo) - len(articles)
        result["new_articles"] = db.insert_articles(conn, articles)
        return result
    finally:
        try:
            db.log_run(conn, **result)
        finally:
            conn.close()


def run_ingest(sources=None):
    sources = sources or list(SITES)
    # Make sure the schema exists once before the parallel workers race to create it.
    db.connect().close()
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        results = list(pool.map(ingest_site, sources))
    return {"new_articles": sum(r["new_articles"] for r in results), "sites": results}
