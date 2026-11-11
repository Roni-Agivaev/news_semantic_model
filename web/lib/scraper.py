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

# Section pages get a longer window: i24's section page needed 10 s and 20 s on the
# 2026-11-09 runs and was still a shell after 20 s on 2026-11-10. Articles keep the
# shorter one, since 4 run in parallel and each bad article would wait the full window.
SECTION_RETRY_AT_S = (0, 5, 10, 15, 20, 30, 40)

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
    Returns (links, attempts made).

    i24 answers a cold cache with an empty JavaScript shell, so a page without
    links is fetched again across `schedule` rather than taken for the end of
    the section."""
    attempts = 0
    for _ in _attempts(schedule):
        attempts += 1
        links = _links_on_page(site, fetch(page_url))
        if links:
            return links, attempts
    return [], attempts


def _reason(e):
    """A short, readable cause for a failed fetch."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    if status:
        return f"HTTP {status}"
    return f"{type(e).__name__}: {e}"[:200]


def get_links(source, schedule=SECTION_RETRY_AT_S, known=None, max_pages=MAX_PAGES, log=None):
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
    pagination degrades to reading page 1 instead of losing the site.

    `log`, if given, is called as log(level, step, message, url=None, **detail)
    for every page read and for the reason the walk ended (lib/events.py)."""
    log = log or _no_log
    site = SITES[source]
    links, seen = [], set()
    paginated = bool(site.get("page_url"))
    for i, page_url in enumerate(_page_urls(site, max_pages)):
        n = i + 1
        started = time.monotonic()
        try:
            page, attempts = _fetch_links(site, page_url, schedule)
        except Exception as e:
            if i == 0:
                raise
            log("warn", "section", f"Page {n} failed ({_reason(e)}); keeping pages 1-{i}", url=page_url, page=n)
            break
        seconds = round(time.monotonic() - started, 1)
        if not page:
            level = "warn" if i == 0 else "info"
            what = "no article links - the site may be blocking or showing an empty shell" if i == 0                 else "no links - end of the section"
            log(level, "section", f"Page {n}: {what}", url=page_url,
                page=n, links=0, attempts=attempts, seconds=seconds)
            break
        fresh = [u for u in page if u not in seen]
        seen.update(fresh)
        links += fresh
        # Only `fresh` needs asking about: the rest of the page was already
        # collected earlier in this walk, so it is accounted for either way.
        stored = known(fresh) if known and fresh else set()
        new = len([u for u in fresh if u not in stored])
        log("info", "section", f"Page {n}: {len(page)} links, {new} not stored yet", url=page_url,
            page=n, links=len(page), new=new, attempts=attempts, seconds=seconds)
        if all(u in stored for u in fresh):
            if paginated:
                log("info", "section", f"Stopped after page {n}: nothing new on it")
            break
        if paginated and n == max_pages:
            log("info", "section", f"Stopped at the page limit ({max_pages})")
    return links


def _no_log(level, step, message, url=None, **detail):
    pass


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


def clean_text(text):
    """Decode HTML entities that some sites leave encoded inside JSON-LD
    (Channel 13 sends &quot; and &#039; in articleBody) and turn non-breaking
    spaces into plain ones."""
    return html_lib.unescape(text).replace("\xa0", " ").strip()


def parse_article(html):
    """Extract title, content and published date from an article page."""
    soup = BeautifulSoup(html, "html.parser")
    ld = _news_article_ld(soup)

    title = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    elif ld.get("headline"):
        title = clean_text(ld["headline"])
    else:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()

    # Prefer the article body the site itself declares; fall back to paragraphs.
    content = clean_text(ld.get("articleBody") or "")
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


def scrape_article(source, url, schedule=RETRY_AT_S, fallback=None, log=None):
    """Fetch and parse one article. Returns a dict, or None if it isn't usable.

    i24 answers a cache miss with an empty JavaScript shell and only serves the
    rendered article 10-15 s later, so an empty result is retried across RETRY_AT_S.

    If the page can't be read and `fallback` (sitemap title/date) is given, a
    title-only article with empty content is returned instead.

    `log` (see get_links) gets one event: scraped, title only, or failed with the reason."""
    log = log or _no_log
    started = time.monotonic()
    attempts, reason = 0, "no attempt made"
    for _ in _attempts(schedule):
        attempts += 1
        try:
            article = parse_article(fetch(url))
        except requests.exceptions.HTTPError as e:
            reason = _reason(e)
            break  # blocked or gone; retrying won't help
        except Exception as e:
            reason = _reason(e)
            continue  # timeout / connection error: retry
        if not article["title"]:
            reason = "page has no title"
        elif len(article["content"]) < MIN_CONTENT_CHARS:
            reason = f"text too short ({len(article['content'])} chars)"
        else:
            article["source"] = source
            article["url"] = url
            log("info", "article", f"Scraped: {article['title']}", url=url,
                attempts=attempts, seconds=round(time.monotonic() - started, 1),
                chars=len(article["content"]))
            return article
    seconds = round(time.monotonic() - started, 1)
    if fallback and fallback.get("title"):
        log("warn", "article", f"Saved title only ({reason}): {fallback['title']}", url=url,
            attempts=attempts, seconds=seconds)
        return {"source": source, "url": url, "title": fallback["title"], "content": "",
                "published_at": fallback.get("published_at")}
    log("error", "article", f"Failed: {reason}", url=url, attempts=attempts, seconds=seconds)
    return None
