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
        # Google News sitemap: lists new articles with title and date.
        "sitemap_url": "https://www.kan.org.il/media/sitemap/news/sitemap.xml",
        # Kan's Cloudflare returns 403 to datacenter IPs (Vercel), sitemap included,
        # so the Vercel cron skips it; run_local_kan.bat scrapes it from a home PC.
        "server_blocked": True,
    },
    "Channel 13": {
        "category_url": "https://13tv.co.il/news/politics/security/",
        "link_pattern": r"/item/news/politics/security/[A-Za-z0-9\-]+/?",
        "base": "https://13tv.co.il",
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
    },
    "Channel 12": {
        "category_url": "https://www.mako.co.il/news-military",
        "link_pattern": r"/news-military/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
        "base": "https://www.mako.co.il",
    },
}

MIN_CONTENT_CHARS = 50


def fetch(url, timeout=20):
    resp = requests.get(url, impersonate="chrome", timeout=timeout)
    resp.raise_for_status()
    return resp.text


def get_links(source):
    """Return the unique, absolute article URLs listed on a site's category page."""
    site = SITES[source]
    html = fetch(site["category_url"])
    links = []
    seen = set()
    for path in re.findall(site["link_pattern"], html):
        # strip a full domain if the regex matched inside an absolute href
        url = site["base"] + path if path.startswith("/") else path
        if url not in seen:
            seen.add(url)
            links.append(url)
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
        # Kan's on-page format, e.g. "16.10.2026 02:59:05"
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
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


def scrape_article(source, url, attempts=3, retry_delay=3, fallback=None):
    """Fetch and parse one article. Returns a dict, or None if it isn't usable.

    i24 answers a cache miss with an empty JavaScript shell and only serves the
    rendered article a few seconds later, so an empty result is retried.

    If the page can't be read and `fallback` (sitemap title/date) is given, a
    title-only article with empty content is returned instead."""
    for attempt in range(attempts):
        if attempt:
            time.sleep(retry_delay)
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
