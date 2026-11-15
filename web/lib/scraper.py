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

TOPICS = ("defense", "politics")
# "defense" for the defense topic; politics sections say whether the outlet's
# section is domestic politics, diplomacy, or one section mixing both.
SECTION_NAMES = ("defense", "domestic", "diplomatic", "combined")


def _section(name, category_url, link_pattern, page_url=None, rss_url=None):
    s = {"name": name, "category_url": category_url, "link_pattern": link_pattern}
    if page_url:
        s["page_url"] = page_url
    if rss_url:
        s["rss_url"] = rss_url
    return s


# Kan's Cloudflare returns 403 to Vercel's IPs, sitemap included, so the Vercel
# cron skips it; .github/workflows/kan-daily.yml scrapes it instead. Its Google
# News sitemap lists new articles of every section with title and date.
_KAN = {"base": "https://www.kan.org.il", "server_blocked": True,
        "sitemap_url": "https://www.kan.org.il/media/sitemap/news/sitemap.xml"}

# topic -> source -> {base, sections, [sitemap_url], [server_blocked]}
# A section: name, category_url, regex for article links on it, and optionally
# page_url (pages 2..N, "{n}") or rss_url (read the feed instead of the page).
# Sources added 2026-11-15 were probed live; see
# docs/superpowers/specs/2026-11-15-politics-pipeline-design.md
SITES = {
    "defense": {
        "Ynet": {"base": "https://www.ynet.co.il", "sections": [
            _section("defense", "https://www.ynet.co.il/news/category/344", r"/news/article/[A-Za-z0-9]+")]},
        "Kan News": {**_KAN, "sections": [
            _section("defense", "https://www.kan.org.il/content/kan-news/defense/",
                     r"/content/kan-news/defense/\d+/?",
                     page_url="https://www.kan.org.il/content/kan-news/defense/?page={n}")]},
        "Channel 13": {"base": "https://13tv.co.il", "sections": [
            _section("defense", "https://13tv.co.il/news/politics/security/",
                     r"/item/news/politics/security/[A-Za-z0-9\-]+/?",
                     page_url="https://13tv.co.il/news/politics/security/page/{n}/")]},
        "Channel 14": {"base": "https://www.c14.co.il", "sections": [
            _section("defense", "https://www.c14.co.il/archive/990", r"/article/\d+")]},
        "I24 NEWS": {"base": "https://www.i24news.tv", "sections": [
            _section("defense", "https://www.i24news.tv/he/news/news/defense-news",
                     r"/he/news/news/defense-news/artc-[A-Za-z0-9]+",
                     page_url="https://www.i24news.tv/he/news/news/defense-news?page={n}")]},
        "Channel 12": {"base": "https://www.mako.co.il", "sections": [
            _section("defense", "https://www.mako.co.il/news-military",
                     r"/news-military/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
                     page_url="https://www.mako.co.il/news-military?page={n}")]},
        "Maariv": {"base": "https://www.maariv.co.il", "sections": [
            _section("defense", "https://www.maariv.co.il/news/military", r"/news/military/article-\d+")]},
        "Israel Hayom": {"base": "https://www.israelhayom.co.il", "sections": [
            _section("defense", "https://www.israelhayom.co.il/news/defense", r"/news/defense/article/\d+",
                     page_url="https://www.israelhayom.co.il/news/defense/page/{n}")]},
        "JDN": {"base": "https://www.jdn.co.il", "sections": [
            _section("defense", "https://www.jdn.co.il/category/news/military/",
                     r"https://www\.jdn\.co\.il/news/\d+/",
                     page_url="https://www.jdn.co.il/category/news/military/page/{n}/")]},
        "Zman Israel": {"base": "https://www.zman.co.il", "sections": [
            _section("defense", "https://www.zman.co.il/feed/561/", r"https://www\.zman\.co\.il/\d{6}/",
                     page_url="https://www.zman.co.il/feed/561/page/{n}/")]},
        "Davar": {"base": "https://www.davar1.co.il", "sections": [
            _section("defense",
                     "https://www.davar1.co.il/topic/%D7%A6%D7%91%D7%90-%D7%95%D7%91%D7%99%D7%98%D7%97%D7%95%D7%9F/",
                     r"https://www\.davar1\.co\.il/\d{6}/")]},
    },
    "politics": {
        # Without JavaScript Ynet's politics page shows the defense list, so its feed is read.
        "Ynet": {"base": "https://www.ynet.co.il", "sections": [
            _section("combined", "https://www.ynet.co.il/news/category/185", r"/news/article/[A-Za-z0-9]+",
                     rss_url="https://www.ynet.co.il/Integration/StoryRss185.xml")]},
        "Kan News": {**_KAN, "sections": [
            _section("combined", "https://www.kan.org.il/content/kan-news/politic/",
                     r"/content/kan-news/politic/\d+/?",
                     page_url="https://www.kan.org.il/content/kan-news/politic/?page={n}")]},
        "Channel 13": {"base": "https://13tv.co.il", "sections": [
            _section("domestic", "https://13tv.co.il/news/politics/politics/",
                     r"/item/news/politics/politics/[A-Za-z0-9\-]+/?",
                     page_url="https://13tv.co.il/news/politics/politics/page/{n}/"),
            _section("diplomatic", "https://13tv.co.il/news/politics/state-policy/",
                     r"/item/news/politics/state-policy/[A-Za-z0-9\-]+/?",
                     page_url="https://13tv.co.il/news/politics/state-policy/page/{n}/")]},
        "Channel 14": {"base": "https://www.c14.co.il", "sections": [
            _section("combined", "https://www.c14.co.il/archive/65839", r"/article/\d+")]},
        "I24 NEWS": {"base": "https://www.i24news.tv", "sections": [
            _section("combined", "https://www.i24news.tv/he/news/news/politics",
                     r"/he/news/news/politics/artc-[A-Za-z0-9]+")]},
        "Channel 12": {"base": "https://www.mako.co.il", "sections": [
            _section("domestic", "https://www.mako.co.il/news-politics",
                     r"/news-politics/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
                     page_url="https://www.mako.co.il/news-politics?page={n}"),
            _section("diplomatic", "https://www.mako.co.il/news-diplomatic",
                     r"/news-diplomatic/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
                     page_url="https://www.mako.co.il/news-diplomatic?page={n}")]},
        "Maariv": {"base": "https://www.maariv.co.il", "sections": [
            _section("combined", "https://www.maariv.co.il/news/politics", r"/news/politics/article-\d+")]},
        "Israel Hayom": {"base": "https://www.israelhayom.co.il", "sections": [
            _section("domestic", "https://www.israelhayom.co.il/news/politics", r"/news/politics/article/\d+",
                     page_url="https://www.israelhayom.co.il/news/politics/page/{n}"),
            _section("diplomatic", "https://www.israelhayom.co.il/news/geopolitics",
                     r"/news/geopolitics/article/\d+",
                     page_url="https://www.israelhayom.co.il/news/geopolitics/page/{n}")]},
        "JDN": {"base": "https://www.jdn.co.il", "sections": [
            _section("domestic", "https://www.jdn.co.il/category/news/politics/",
                     r"https://www\.jdn\.co\.il/news/\d+/",
                     page_url="https://www.jdn.co.il/category/news/politics/page/{n}/"),
            _section("diplomatic", "https://www.jdn.co.il/category/news/state/",
                     r"https://www\.jdn\.co\.il/news/\d+/",
                     page_url="https://www.jdn.co.il/category/news/state/page/{n}/")]},
        "Zman Israel": {"base": "https://www.zman.co.il", "sections": [
            _section("combined", "https://www.zman.co.il/feed/609/", r"https://www\.zman\.co\.il/\d{6}/",
                     page_url="https://www.zman.co.il/feed/609/page/{n}/")]},
    },
}


def _check_topic(topic):
    if topic not in SITES:
        raise ValueError(f"unknown topic {topic!r}; expected one of {', '.join(TOPICS)}")


def sources(topic):
    """Every source scraped for a topic, in registry order."""
    _check_topic(topic)
    return list(SITES[topic])


def server_sources(topic):
    """The sources the Vercel cron can reach (the rest run from GitHub Actions)."""
    _check_topic(topic)
    return [s for s, site in SITES[topic].items() if not site.get("server_blocked")]


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


def _walk_section(section, schedule, known, max_pages, log):
    """Return the unique, absolute article URLs listed in one section.

    Sections with a `page_url` are walked page by page; the rest read their
    category page alone. The walk stops before page N+1 once every link on
    page N is accounted for - already seen in this walk, or reported stored by
    `known` - and at `max_pages` either way. It also stops on a page with no
    links at all.

    Page 1 is the section itself, so a failure there is raised for the caller to
    record. A later page that cannot be fetched only ends the walk, so broken
    pagination degrades to reading page 1 instead of losing the section."""
    links, seen = [], set()
    paginated = bool(section.get("page_url"))
    for i, page_url in enumerate(_page_urls(section, max_pages)):
        n = i + 1
        started = time.monotonic()
        try:
            page, attempts = _fetch_links(section, page_url, schedule)
        except Exception as e:
            if i == 0:
                raise
            log("warn", "section", f"Page {n} failed ({_reason(e)}); keeping pages 1-{i}", url=page_url, page=n)
            break
        seconds = round(time.monotonic() - started, 1)
        if not page:
            level = "warn" if i == 0 else "info"
            what = ("no article links - the site may be blocking or showing an empty shell" if i == 0
                    else "no links - end of the section")
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


def _matches(section, url):
    """True when a full URL is an article link of this section."""
    pattern = section["link_pattern"]
    if not pattern.startswith("http"):
        pattern = re.escape(section["base"]) + pattern
    return re.fullmatch(pattern, url) is not None


def _links_from_rss(xml, section):
    """Article URLs in an RSS feed's <link>/<guid> values, in feed order."""
    urls = []
    for value in re.findall(r"<(?:link|guid)\b[^>]*>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</(?:link|guid)>",
                            xml, flags=re.S):
        url = html_lib.unescape(value).strip()
        if _matches(section, url) and url not in urls:
            urls.append(url)
    return urls


def _read_feed(section, known, log):
    """Links from a section's RSS feed: one fetch, no pagination."""
    started = time.monotonic()
    links = _links_from_rss(fetch(section["rss_url"]), section)
    stored = known(links) if known and links else set()
    new = len([u for u in links if u not in stored])
    level = "info" if links else "warn"
    log(level, "section", f"Feed: {len(links)} links, {new} not stored yet", url=section["rss_url"],
        page=1, links=len(links), new=new, attempts=1, seconds=round(time.monotonic() - started, 1))
    return links


def get_links(topic, source, schedule=SECTION_RETRY_AT_S, known=None, max_pages=MAX_PAGES, log=None):
    """Return [(url, section_name)] for every article a source lists for a topic.

    Each of the source's sections is walked in turn (see _walk_section, or the
    feed for an `rss_url` section). A URL listed by two sections is kept once,
    tagged with the first.

    `known` is an optional callable taking URLs and returning the subset
    already stored. It is how the database reaches this module, which imports
    nothing from db.py. With `known=None` nothing counts as stored, so only a
    repeated page, an empty page or `max_pages` ends a walk; that is the deep
    walk web/backfill.py wants.

    A section that fails is logged and skipped while another section of the
    source still works; when every section fails the last error is raised, so
    the caller records the source as failed.

    `log`, if given, is called as log(level, step, message, url=None, **detail)
    for every page read and for the reason a walk ended (lib/events.py). With
    several sections each message starts with "[section] "."""
    log = log or _no_log
    _check_topic(topic)
    site = SITES[topic][source]
    sections = site["sections"]
    tagged, seen, error = [], set(), None
    for section in sections:
        sec = {**section, "base": site["base"]}
        slog = log
        if len(sections) > 1:
            def slog(level, step, message, url=None, _name=sec["name"], **detail):
                log(level, step, f"[{_name}] {message}", url=url, **detail)
        try:
            if sec.get("rss_url"):
                urls = _read_feed(sec, known, slog)
            else:
                urls = _walk_section(sec, schedule, known, max_pages, slog)
        except Exception as e:
            error = e
            if len(sections) > 1:
                log("warn", "section", f"Section {sec['name']} failed ({_reason(e)})",
                    url=sec.get("rss_url") or sec["category_url"])
            continue
        for url in urls:
            if url not in seen:
                seen.add(url)
                tagged.append((url, sec["name"]))
    if error is not None and not tagged:
        raise error
    return tagged


def _no_log(level, step, message, url=None, **detail):
    pass


def get_sitemap_entries(topic, source):
    """Read a source's Google News sitemap. Returns
    {url: {"title", "published_at", "section"}} for the URLs matching one of the
    source's sections for `topic` (the first section that matches)."""
    _check_topic(topic)
    site = SITES[topic][source]
    sections = [{**s, "base": site["base"]} for s in site["sections"]]
    xml = fetch(site["sitemap_url"])
    entries = {}
    for block in re.findall(r"<url\b.*?</url>", xml, flags=re.S):
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", block)
        if not loc:
            continue
        url = loc.group(1)
        section = next((s["name"] for s in sections if _matches(s, url)), None)
        if section is None:
            continue
        title = re.search(r"<news:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</news:title>", block, flags=re.S)
        date = re.search(r"<news:publication_date>\s*([^<]+?)\s*</news:publication_date>", block)
        entries[url] = {
            "title": html_lib.unescape(title.group(1)).strip() if title else None,
            "published_at": parse_date(date.group(1)) if date else None,
            "section": section,
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


# Kan's page chrome that ends up among the article paragraphs.
_SIGN_IN_PROMPT = "התחברו וקבלו תוכן מותאם אישית"
_FOOTER_MARKER = "Website created by IdeoDigital"


def strip_boilerplate(text):
    """Remove site chrome that is not part of the article (Kan's repeated
    sign-in prompt, and its footer with everything after it)."""
    text = text.split(_FOOTER_MARKER, 1)[0].replace(_SIGN_IN_PROMPT, " ")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


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
    content = strip_boilerplate(content)

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
