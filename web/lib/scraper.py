"""
Browser-free scrapers for the 6 news sites.

Every site renders its category page and articles server-side, and every article
carries a schema.org NewsArticle JSON-LD block with datePublished, so a single
generic extractor works for all of them. curl_cffi impersonates Chrome's TLS
fingerprint, which is what gets us past Channel 13's and Mako's bot checks.
"""
import html as html_lib
import json
import re
import time
from datetime import datetime, timezone, timedelta

from bs4 import BeautifulSoup
from curl_cffi import requests

ISRAEL_TZ = timezone(timedelta(hours=3))  # only used as a fallback when a date has no offset

# name -> category page, regex for article links on that page, base url
SITES = {
    "Ynet": {
        "category_url": "https://www.ynet.co.il/news/category/344",
        "link_pattern": r"/news/article/[A-Za-z0-9]+",
        "base": "https://www.ynet.co.il",
    },
    "Kan News": {
        "category_url": "https://www.kan.org.il/content/kan-news/defense/",
        "link_pattern": r"/content/kan-news/defense/\d+/?",
        "base": "https://www.kan.org.il",
        "page_url": "https://www.kan.org.il/content/kan-news/defense/?page={n}",
        # Google News sitemap: lists new articles with title and date.
        "sitemap_url": "https://www.kan.org.il/media/sitemap/news/sitemap.xml",
        # Kan's Cloudflare returns 403 to Vercel's IPs, sitemap included, so the
        # Vercel cron skips it; .github/workflows/kan-daily.yml scrapes it instead.
        "server_blocked": True,
    },
    "Channel 13": {
        "category_url": "https://13tv.co.il/news/politics/security/",
        "link_pattern": r"/item/news/politics/security/[A-Za-z0-9\-]+/?",
        "base": "https://13tv.co.il",
        "page_url": "https://13tv.co.il/news/politics/security/page/{n}/",
    },
    "Channel 14": {
        "category_url": "https://www.c14.co.il/archive/990",
        "link_pattern": r"/article/\d+",
        "base": "https://www.c14.co.il",
    },
    "I24 NEWS": {
        "category_url": "https://www.i24news.tv/he/news/news/defense-news",
        "link_pattern": r"/he/news/news/defense-news/artc-[A-Za-z0-9]+",
        "base": "https://www.i24news.tv",
        "page_url": "https://www.i24news.tv/he/news/news/defense-news?page={n}",
    },
    "Channel 12": {
        "category_url": "https://www.mako.co.il/news-military",
        "link_pattern": r"/news-military/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
        "base": "https://www.mako.co.il",
        "page_url": "https://www.mako.co.il/news-military?page={n}",
    },
}

MIN_CONTENT_CHARS = 50

# i24 answers a cold edge-cache miss with a ~7 KB JavaScript shell and serves the
# rendered page only 10-15 s later (measured 2026-11-06: the section page was still
# a shell at 0/3/6 s and complete at 10 s; articles first parsed at 1 s, 11 s, 15.6 s).
# Every attempt inside that window gets the same shell, so the retries have to span it.
RETRY_AT_S = (0, 5, 10, 15, 20)  # when each attempt starts, seconds from the first

# How many pages of a section the daily cron walks. About 15-18 days of history
# at the measured 5-6 days per page, so a two-week outage heals itself. This is a
# choice about unattended recovery, not a measured value; web/backfill.py goes deeper.
MAX_PAGES = 3


def _attempts(schedule=RETRY_AT_S):
    """Yield once per attempt, sleeping so attempt n starts schedule[n] seconds in."""
    for i, at in enumerate(schedule):
        if i:
            time.sleep(at - schedule[i - 1])
        yield at


def fetch(url, timeout=20):
    resp = requests.get(url, impersonate="chrome", timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _page_urls(site, max_pages):
    """The section's page 1, then its paginated siblings if it has any."""
    yield site["category_url"]
    template = site.get("page_url")
    if template:
        for n in range(2, max_pages + 1):
            yield template.format(n=n)


def _links_on_page(site, html):
    """The absolute article URLs matching this site's pattern, in page order."""
    urls, seen = [], set()
    for path in re.findall(site["link_pattern"], html):
        # strip a full domain if the regex matched inside an absolute href
        url = site["base"] + path if path.startswith("/") else path
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _fetch_links(site, page_url, schedule):
    """Fetch one section page, retrying while it has no links.

    i24 answers a cold cache with an empty JavaScript shell, so a page without
    links is fetched again across `schedule` rather than taken for the end of
    the section."""
    for _ in _attempts(schedule):
        links = _links_on_page(site, fetch(page_url))
        if links:
            return links
    return []


def get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES):
    """Return the unique, absolute article URLs listed in a site's section.

    Sites with a `page_url` are walked page by page; the rest read their
    category page alone. The walk stops before page N+1 once every link on
    page N is accounted for - already seen in this walk, or reported stored by
    `known` - and at `max_pages` either way. It also stops on a page with no
    links at all.

    `known` is an optional callable taking URLs and returning the subset
    already stored. It is how the database reaches this module, which imports
    nothing from db.py. With `known=None` nothing counts as stored, so only a
    repeated page, an empty page or `max_pages` ends the walk; that is the deep
    walk web/backfill.py wants.

    Page 1 is the section itself, so a failure there is raised for the caller to
    record. A later page that cannot be fetched only ends the walk, so broken
    pagination degrades to reading page 1 instead of losing the site."""
    site = SITES[source]
    links, seen = [], set()
    for i, page_url in enumerate(_page_urls(site, max_pages)):
        try:
            page = _fetch_links(site, page_url, schedule)
        except Exception:
            if i == 0:
                raise
            break
        if not page:
            break
        fresh = [u for u in page if u not in seen]
        seen.update(fresh)
        links += fresh
        # Only `fresh` needs asking about: the rest of the page was already
        # collected earlier in this walk, so it is accounted for either way.
        stored = known(fresh) if known and fresh else set()
        if all(u in stored for u in fresh):
            break
    return links


def get_sitemap_entries(source):
    """Read a site's Google News sitemap. Returns {url: {"title", "published_at"}}
    for the URLs that match the site's article pattern."""
    site = SITES[source]
    xml = fetch(site["sitemap_url"])
    entries = {}
    for block in re.findall(r"<url\b.*?</url>", xml, flags=re.S):
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", block)
        if not loc:
            continue
        url = loc.group(1)
        if not re.fullmatch(re.escape(site["base"]) + site["link_pattern"], url):
            continue
        title = re.search(r"<news:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</news:title>", block, flags=re.S)
        date = re.search(r"<news:publication_date>\s*([^<]+?)\s*</news:publication_date>", block)
        entries[url] = {
            "title": html_lib.unescape(title.group(1)).strip() if title else None,
            "published_at": parse_date(date.group(1)) if date else None,
        }
    return entries


def parse_date(value):
    """Parse the date formats the sites use into an aware datetime (or None)."""
    if not value:
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        dt = None
        # Kan's on-page format, e.g. "16.10.2026 02:59:05", and the old CSVs' "06/04/2026 14:40"
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
                    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ISRAEL_TZ)
    return dt


def _news_article_ld(soup):
    """Find the NewsArticle object among the page's JSON-LD blocks."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data])
        for item in items:
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(t in ("NewsArticle", "Article", "ReportageNewsArticle") for t in types):
                return item
    return {}


def parse_article(html):
    """Extract title, content and published date from an article page."""
    soup = BeautifulSoup(html, "html.parser")
    ld = _news_article_ld(soup)

    title = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    elif ld.get("headline"):
        title = ld["headline"].strip()
    else:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # Prefer the article body the site itself declares; fall back to paragraphs.
    content = (ld.get("articleBody") or "").strip()
    if len(content) < MIN_CONTENT_CHARS:
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        content = " ".join(p for p in paragraphs if len(p) > 15)

    published = ld.get("datePublished")
    if not published:
        meta = soup.find("meta", property="article:published_time")
        published = meta.get("content") if meta else None
    if not published:
        time_tag = soup.find("time", attrs={"datetime": True})
        published = time_tag["datetime"] if time_tag else None

    return {"title": title, "content": content, "published_at": parse_date(published)}


def scrape_article(source, url, schedule=RETRY_AT_S, fallback=None):
    """Fetch and parse one article. Returns a dict, or None if it isn't usable.

    i24 answers a cache miss with an empty JavaScript shell and only serves the
    rendered article 10-15 s later, so an empty result is retried across RETRY_AT_S.

    If the page can't be read and `fallback` (sitemap title/date) is given, a
    title-only article with empty content is returned instead."""
    for _ in _attempts(schedule):
        try:
            article = parse_article(fetch(url))
        except requests.exceptions.HTTPError:
            break  # blocked or gone; retrying won't help
        except Exception:
            continue  # timeout / connection error: retry
        if article["title"] and len(article["content"]) >= MIN_CONTENT_CHARS:
            article["source"] = source
            article["url"] = url
            return article
    if fallback and fallback.get("title"):
        return {"source": source, "url": url, "title": fallback["title"], "content": "",
                "published_at": fallback.get("published_at")}
    return None
