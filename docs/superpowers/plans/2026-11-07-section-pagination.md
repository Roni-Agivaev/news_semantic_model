# Section Pagination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read every article in each site's defense section instead of only page 1, and recover the 245 articles already missing from the database.

**Architecture:** `get_links` in `web/lib/scraper.py` grows from "fetch one category page" into a page walk. Three sites get an optional `page_url` format string; sites without one behave exactly as today. The walk stops adaptively — once a page adds nothing the database does not already have — so the daily cron normally pays one or two extra category fetches, while an outage heals itself by walking deeper. A one-off local script runs the same ingestion with a much deeper cap to recover the historical gap.

**Tech Stack:** Python 3.11+, `curl_cffi` (Chrome TLS impersonation), BeautifulSoup, `psycopg` 3 against Supabase Postgres, stdlib `unittest`, Vercel Python serverless functions.

**Spec:** [`docs/superpowers/specs/2026-11-06-section-pagination-design.md`](../specs/2026-11-06-section-pagination-design.md)

## Global Constraints

- The daily cron must stay inside Vercel's 300 s `maxDuration` (`web/vercel.json`, `api/cron.py`).
- No new dependency. `web/requirements.txt` stays at `beautifulsoup4==4.13.4`, `curl-cffi==0.11.4`, `psycopg[binary]==3.2.9`.
- Tests: stdlib `unittest`, no network, no database. Deterministic — patch `time.sleep`, never really sleep.
- No schema change. Backfilled rows are ordinary `origin='scraper'` articles.
- No keyword or topic filtering anywhere. Section membership is the only criterion.
- Ynet, Channel 14 and Kan News must keep fetching exactly one page.
- `scraper.py` imports nothing from `db.py`. The database reaches it only as an injected callable.
- Never print or echo `DATABASE_URL`, `CRON_SECRET`, `DASHBOARD_PASSWORD` or `GITHUB_TOKEN`, or any value out of `web/.env`.
- Commits are local. Do not `git push` without asking — pushing to `origin/main` triggers a Vercel production deploy.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `web/lib/scraper.py` | HTTP fetching, link extraction, article parsing. The page walk lives here. | Modify: `SITES` (+`page_url` ×3), new `MAX_PAGES`, `_page_urls`, `_links_on_page`, `_fetch_links`; rewrite `get_links`. |
| `web/lib/ingest.py` | One ingestion run: links → skip known → scrape → insert → log. Owns the database connection, so it owns the `known` callable. | Modify: `ingest_site` and `run_ingest` gain `max_pages` / `stop_at_known`. |
| `web/backfill.py` | One-off CLI for the deep walk. Not deployed — only `api/*.py` become Vercel functions. | Create. |
| `web/tests/test_scraper_pagination.py` | Everything about the walk: depth, stop rule, cap, failure handling, time budget. | Create. |
| `web/tests/test_scraper_retry.py` | The cold-cache retry window. Already written; must stay green. | No change. |
| `web/README.md` | Operator documentation. | Modify: pagination in "How it works", `backfill.py` in "Local tools". |

`web/lib/db.py`, `web/api/cron.py` and `web/run_local.py` are **not** modified. Both callers of `run_ingest` pass only the first argument positionally, so keyword parameters with defaults reach them safely.

---

### Task 1: A working test environment, and land the i24 retry fix

The repository's `.venv` was copied from another computer and is broken — it points at `C:\Users\roni1\...\Python311\python.exe`, which does not exist here. Nothing in this plan can be verified until that is fixed. `.venv/` is gitignored, so this is a local-only step.

The i24 cold-cache retry fix is already in the working tree, uncommitted, with its tests. The backfill in Task 5 cannot read i24 at all without it, so it lands first.

**Files:**
- Modify: nothing (the fix is already written)
- Test: `web/tests/test_scraper_retry.py` (already written)

**Interfaces:**
- Consumes: nothing
- Produces: `RETRY_AT_S = (0, 5, 10, 15, 20)` and `_attempts(schedule=RETRY_AT_S)` in `web/lib/scraper.py`, committed. Every later task's page fetch goes through `_attempts`.

- [ ] **Step 1: Recreate the virtual environment**

PowerShell, from the repository root (`news_semantic_model`):

```powershell
Remove-Item -Recurse -Force .venv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r web\requirements.txt
```

(In bash the interpreter is `.venv/Scripts/python.exe` — same path, forward slashes.)

- [ ] **Step 2: Confirm the scraper's dependencies import**

```powershell
.venv\Scripts\python.exe -c "import bs4, curl_cffi, psycopg; print('deps ok')"
```

Expected: `deps ok`. A `ModuleNotFoundError` means step 1's install did not finish — rerun it rather than continuing.

- [ ] **Step 3: Run the existing retry tests**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_retry.py
```

Expected: 3 tests, `OK`. Run the file directly — `unittest discover` fails with "Start directory is not importable" because `web/tests/` has no `__init__.py`, and that is deliberate.

- [ ] **Step 4: Review the diff that is about to be committed**

```powershell
git diff web/lib/scraper.py
```

Expected: `RETRY_AT_S` and `_attempts` added; `get_links` and `scrape_article` taking `schedule=RETRY_AT_S` in place of `attempts=3, retry_delay=3`; their retry loops now `for _ in _attempts(schedule):`. Roughly 21 insertions, 11 deletions.

- [ ] **Step 5: Commit**

```bash
git add web/lib/scraper.py web/tests/test_scraper_retry.py docs/
git commit -m "Span i24's cold-cache render window when retrying

i24 answers a cold edge-cache miss with a ~7 KB JavaScript shell and
serves the rendered page only 10-15 s later. The previous retry made
three attempts at 0/3/6 s, entirely inside that window, so every
attempt got the same shell. Retry at 0/5/10/15/20 s instead.

Adds the design spec and plan for reading whole sections, and tests
that drive the scraper against a page rendering at 12 s on a virtual
clock.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Walk paginated sections up to a cap

**Files:**
- Modify: `web/lib/scraper.py:20-57` (`SITES`), `web/lib/scraper.py:82-100` (`get_links`)
- Test: `web/tests/test_scraper_pagination.py` (create)

**Interfaces:**
- Consumes: `_attempts(schedule=RETRY_AT_S)`, `fetch(url, timeout=20)`, `SITES` from Task 1.
- Produces:
  - `MAX_PAGES = 3` — module constant in `web/lib/scraper.py`.
  - `get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES) -> list[str]` — absolute article URLs, page order, deduplicated. `known` is unused until Task 4 but is in the signature from here so no caller has to change twice.
  - `SITES[name]["page_url"]` — optional `str.format` template taking `{n}`, present only on Channel 13, Channel 12 and I24 NEWS.

- [ ] **Step 1: Write the failing test**

Create `web/tests/test_scraper_pagination.py`:

```python
"""
Three of the six sites paginate their defense section, so reading only the
category page left 245 section articles uncollected (measured 2026-11-06).
These tests drive the page walk against fake sites: no network, no database,
and time.sleep patched so the cold-cache retries cost nothing.
"""
import os
import sys
import unittest
from collections import Counter
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import scraper  # noqa: E402

WALK_BUDGET_S = 75.0  # one site's whole category walk, against the cron's 300 s

# Channel 13 is the stand-in paginated site throughout: its link pattern is
# r"/item/news/politics/security/[A-Za-z0-9\-]+/?"
SOURCE = "Channel 13"
PAGE_1 = "https://13tv.co.il/news/politics/security/"
SHELL = "<html><head><title>13</title></head><body><div id=root></div></body></html>"


def page_n(n):
    return f"https://13tv.co.il/news/politics/security/page/{n}/"


def section_page(*ids):
    """A category page listing the given article ids, in order."""
    links = "".join(f'<a href="/item/news/politics/security/{i}/">x</a>' for i in ids)
    return f"<html><body>{links}</body></html>"


def article_urls(*ids):
    return [f"https://13tv.co.il/item/news/politics/security/{i}/" for i in ids]


class FakeSite:
    """Serves prepared HTML per URL. A URL with nothing prepared is past the end
    of the section and comes back link-free, which is what the real sites do."""

    def __init__(self, pages, shell_attempts=0):
        self.pages = pages
        self.shell_attempts = shell_attempts  # per URL, before the real page
        self.requested = []
        self._attempts = Counter()

    def fetch(self, url, timeout=20):
        self.requested.append(url)
        self._attempts[url] += 1
        if self._attempts[url] <= self.shell_attempts:
            return SHELL
        body = self.pages.get(url, SHELL)
        if isinstance(body, Exception):
            raise body
        return body

    @property
    def pages_seen(self):
        """The distinct URLs fetched, in the order they were first requested."""
        return list(dict.fromkeys(self.requested))


class WalkTest(unittest.TestCase):
    def setUp(self):
        self.slept = 0.0

        def sleep(seconds):
            self.slept += seconds

        patch_sleep = mock.patch.object(scraper.time, "sleep", sleep)
        patch_sleep.start()
        self.addCleanup(patch_sleep.stop)

    def walk(self, site, **kwargs):
        with mock.patch.object(scraper, "fetch", site.fetch):
            return scraper.get_links(SOURCE, **kwargs)

    def test_walks_every_page_of_a_paginated_section(self):
        site = FakeSite({
            PAGE_1: section_page("a1", "a2"),
            page_n(2): section_page("b1", "b2"),
            page_n(3): section_page("c1", "c2"),
        })
        links = self.walk(site, max_pages=5)
        self.assertEqual(
            links, article_urls("a1", "a2", "b1", "b2", "c1", "c2"),
            msg=f"walk read {site.pages_seen}")

    def test_stops_at_max_pages_on_a_section_that_never_runs_out(self):
        site = FakeSite({PAGE_1: section_page("a1", "a2"),
                         page_n(2): section_page("b1", "b2"),
                         page_n(3): section_page("c1", "c2"),
                         page_n(4): section_page("d1", "d2")})
        links = self.walk(site, max_pages=3)
        self.assertEqual(site.pages_seen, [PAGE_1, page_n(2), page_n(3)])
        self.assertEqual(links, article_urls("a1", "a2", "b1", "b2", "c1", "c2"))

    def test_a_site_without_page_url_reads_one_page(self):
        """Ynet and Channel 14 return page 1 for ?page=2, so they must not be walked.
        This passes before the walk exists too - it is the regression guard."""
        ynet = FakeSite({"https://www.ynet.co.il/news/category/344":
                         '<html><body><a href="/news/article/abc123">x</a></body></html>'})
        with mock.patch.object(scraper, "fetch", ynet.fetch):
            links = scraper.get_links("Ynet", max_pages=5)
        self.assertEqual(links, ["https://www.ynet.co.il/news/article/abc123"])
        self.assertEqual(ynet.pages_seen, ["https://www.ynet.co.il/news/category/344"])

    def test_walk_stays_within_time_budget(self):
        """Every page cold: each one costs retries, and three of them must still
        leave most of the cron's 300 s for article fetches."""
        site = FakeSite({PAGE_1: section_page("a1"),
                         page_n(2): section_page("b1"),
                         page_n(3): section_page("c1")},
                        shell_attempts=3)
        links = self.walk(site, max_pages=3)
        self.assertEqual(links, article_urls("a1", "b1", "c1"))
        self.assertLessEqual(
            self.slept, WALK_BUDGET_S,
            msg=f"walking 3 cold pages burned {self.slept:.0f}s (budget {WALK_BUDGET_S:.0f}s)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
```

Expected: 4 tests, 4 errors, every one of them

```
TypeError: get_links() got an unexpected keyword argument 'max_pages'
```

because `get_links` is still `get_links(source, schedule=RETRY_AT_S)`. That is the right failure — the parameter is the whole point of the task.

One of the four, `test_a_site_without_page_url_reads_one_page`, is a regression guard rather than a new requirement: it encodes behaviour the scraper already has, and the only thing missing is the parameter. It must pass after step 3 and keep passing forever.

- [ ] **Step 3: Write the implementation**

In `web/lib/scraper.py`, add `page_url` to the three paginated entries in `SITES` — leave Ynet, Kan News and Channel 14 untouched:

```python
    "Channel 13": {
        "category_url": "https://13tv.co.il/news/politics/security/",
        "link_pattern": r"/item/news/politics/security/[A-Za-z0-9\-]+/?",
        "base": "https://13tv.co.il",
        "page_url": "https://13tv.co.il/news/politics/security/page/{n}/",
    },
```

```python
    "I24 NEWS": {
        "category_url": "https://www.i24news.tv/he/news/news/defense-news",
        "link_pattern": r"/he/news/news/defense-news/artc-[A-Za-z0-9]+",
        "base": "https://www.i24news.tv",
        "page_url": "https://www.i24news.tv/he/news/news/defense-news?page={n}",
    },
```

```python
    "Channel 12": {
        "category_url": "https://www.mako.co.il/news-military",
        "link_pattern": r"/news-military/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm",
        "base": "https://www.mako.co.il",
        "page_url": "https://www.mako.co.il/news-military?page={n}",
    },
```

Add the cap next to `RETRY_AT_S`:

```python
# How many pages of a section the daily cron walks. About 15-18 days of history
# at the measured 5-6 days per page, so a two-week outage heals itself. This is a
# choice about unattended recovery, not a measured value; web/backfill.py goes deeper.
MAX_PAGES = 3
```

Replace `get_links` (currently `web/lib/scraper.py:82-100`) with:

```python
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

    Sites with a `page_url` are walked page by page, up to `max_pages`; the rest
    read their category page alone. The walk also stops on the first page with
    no links at all."""
    site = SITES[source]
    links, seen = [], set()
    for page_url in _page_urls(site, max_pages):
        page = _fetch_links(site, page_url, schedule)
        if not page:
            break
        fresh = [u for u in page if u not in seen]
        seen.update(fresh)
        links += fresh
    return links
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
.venv\Scripts\python.exe web\tests\test_scraper_retry.py
```

Expected: 4 tests `OK`, then 3 tests `OK`. The retry tests must still pass — `get_links` keeps its `schedule` parameter and its retry behaviour on page 1.

`test_walk_stays_within_time_budget` should consume exactly 45 virtual seconds: three pages, each shelled for three attempts, at 5 s between attempts. Well under the 75 s budget, and a change that pushes it near the budget means the retry schedule or the cap moved.

- [ ] **Step 5: Check the three live page templates**

The templates were measured on 2026-11-06. Confirm they still return a second page of links before committing — a wrong template is a silent no-op, which is the risk the spec calls out. This is one read-only fetch per site, the same request the scraper makes anyway.

```powershell
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'web'); from lib.scraper import SITES, _fetch_links; [print(n, len(_fetch_links(s, s['page_url'].format(n=2), (0, 5, 10)))) for n, s in SITES.items() if s.get('page_url')]"
```

Expected: a nonzero count for each of `Channel 13`, `I24 NEWS`, `Channel 12` — around 20-35 links each. A `0` means that site's pagination scheme changed; find the current one in the browser before going on. A `Kan News`-style 403 should not appear here, since none of these three is `server_blocked`.

- [ ] **Step 6: Commit**

```bash
git add web/lib/scraper.py web/tests/test_scraper_pagination.py
git commit -m "Walk paginated defense sections, not just page 1

Channel 13, Channel 12 and i24 paginate their defense section; the
ingester only ever read page 1, so 245 section articles were never
collected. Give those three a page_url template and walk up to
MAX_PAGES pages. Sites without the template read one page as before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: A broken page after the first ends the walk instead of failing it

Today a category page that 404s or times out raises out of `get_links`, and `ingest_site` records the run as `category page: HTTPError…` with no links. That is right for page 1 — the section itself is unreachable. It is wrong for page 2: a site changing its pagination scheme would take a site that works today down to zero. The spec requires the walk to degrade to page 1 rather than fail.

**Files:**
- Modify: `web/lib/scraper.py` (`get_links`, as written in Task 2)
- Test: `web/tests/test_scraper_pagination.py` (as written in Task 2)

**Interfaces:**
- Consumes: `get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES)` from Task 2.
- Produces: no signature change. A new behavioural guarantee — `get_links` raises only when page 1 fails.

- [ ] **Step 1: Write the failing tests**

Add to `web/tests/test_scraper_pagination.py`, inside `class WalkTest`, after `test_walk_stays_within_time_budget`:

```python
    def test_a_broken_page_two_keeps_page_ones_links(self):
        """A site changing its pagination scheme must degrade to page 1, not fail."""
        site = FakeSite({PAGE_1: section_page("a1", "a2"),
                         page_n(2): HTTP_ERROR("404")})
        links = self.walk(site, max_pages=3)
        self.assertEqual(links, article_urls("a1", "a2"))
        self.assertEqual(site.pages_seen, [PAGE_1, page_n(2)])

    def test_page_one_failure_still_raises(self):
        """ingest_site relies on this to record a 'category page' error."""
        site = FakeSite({PAGE_1: HTTP_ERROR("403")})
        with self.assertRaises(HTTP_ERROR):
            self.walk(site, max_pages=3)
```

And add what these two need to the top of the file, below `from lib import scraper`. Reach the exception class the way `scraper.py` itself does (`web/lib/scraper.py:211`) rather than importing the submodule, so the name holds across `curl_cffi` versions:

```python
from curl_cffi import requests as curl_requests  # noqa: E402

HTTP_ERROR = curl_requests.exceptions.HTTPError
```

- [ ] **Step 2: Run the tests to verify the first one fails**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
```

Expected: 6 tests, 1 error.

- `test_a_broken_page_two_keeps_page_ones_links` ERRORS with `curl_cffi.requests.exceptions.HTTPError: 404` escaping the walk — page 2's failure is taking the whole site down, which is the regression this task prevents.
- `test_page_one_failure_still_raises` PASSES — it describes behaviour Task 2 already has, and must survive step 3.
- The four tests from Task 2 keep passing.

- [ ] **Step 3: Write the implementation**

In `web/lib/scraper.py`, wrap the fetch inside `get_links`'s loop and extend the docstring:

```python
def get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES):
    """Return the unique, absolute article URLs listed in a site's section.

    Sites with a `page_url` are walked page by page, up to `max_pages`; the rest
    read their category page alone. The walk also stops on the first page with
    no links at all.

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
    return links
```

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
.venv\Scripts\python.exe web\tests\test_scraper_retry.py
```

Expected: 6 tests `OK`, then 3 tests `OK`.

- [ ] **Step 5: Commit**

```bash
git add web/lib/scraper.py web/tests/test_scraper_pagination.py
git commit -m "Let broken pagination degrade to page 1 instead of failing the site

A page after the first that cannot be fetched now ends the walk and
keeps what page 1 gave us. Page 1 still raises, because that is the
section itself and ingest_site records it as a run error.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Stop walking once a page adds nothing new

A fixed depth does not self-heal: it costs the same every run and still leaves a gap after a long outage. The adaptive rule stops at page 1 or 2 in steady state and walks deeper by itself after a failed run. The database reaches `scraper.py` only as an injected callable, so `scraper.py` keeps no database import.

**Files:**
- Modify: `web/lib/scraper.py` (`get_links`)
- Modify: `web/lib/ingest.py:8` (import), `web/lib/ingest.py:17-60` (`ingest_site`), `web/lib/ingest.py:68-74` (`run_ingest`)
- Test: `web/tests/test_scraper_pagination.py`

**Interfaces:**
- Consumes: `get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES)` from Tasks 2-3; `db.existing_urls(conn, urls) -> set[str]` (unchanged, `web/lib/db.py:68`).
- Produces:
  - `known` becomes live: an optional callable `(urls: list[str]) -> set[str]`, returning the subset already stored. `None` means nothing counts as stored.
  - `ingest_site(source, max_pages=MAX_PAGES, stop_at_known=True) -> dict` — same dict as today.
  - `run_ingest(sources=None, max_pages=MAX_PAGES, stop_at_known=True) -> dict` — same dict as today. Task 5 calls it with `max_pages=25, stop_at_known=False`.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/test_scraper_pagination.py`, inside `class WalkTest`:

```python
    def test_stops_before_the_page_after_an_all_known_one(self):
        """Page 2 holds nothing new, so page 3 is never fetched."""
        site = FakeSite({PAGE_1: section_page("a1", "a2"),
                         page_n(2): section_page("b1", "b2"),
                         page_n(3): section_page("c1", "c2")})
        stored = set(article_urls("b1", "b2"))
        asked = []

        def known(urls):
            asked.append(list(urls))
            return {u for u in urls if u in stored}

        links = self.walk(site, known=known, max_pages=5)
        self.assertEqual(site.pages_seen, [PAGE_1, page_n(2)],
                         msg="page 3 should not have been fetched")
        self.assertEqual(links, article_urls("a1", "a2", "b1", "b2"))
        self.assertEqual(asked, [article_urls("a1", "a2"), article_urls("b1", "b2")],
                         msg="known should be asked once per page, about that page's new links")

    def test_a_page_that_only_repeats_earlier_links_ends_the_walk(self):
        """Some sites clamp an out-of-range page back to the last real one."""
        site = FakeSite({PAGE_1: section_page("a1", "a2"),
                         page_n(2): section_page("a1", "a2"),
                         page_n(3): section_page("c1", "c2")})
        links = self.walk(site, max_pages=5)
        self.assertEqual(site.pages_seen, [PAGE_1, page_n(2)])
        self.assertEqual(links, article_urls("a1", "a2"))
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
```

Expected: both FAIL with the same shape — `known` is accepted but ignored, so nothing stops the walk early and it runs on until a page comes back empty:

```
AssertionError: Lists differ: [... 'page/2/', 'page/3/', 'page/4/'] != [... 'page/2/']
-  'https://13tv.co.il/news/politics/security/page/3/',
-  'https://13tv.co.il/news/politics/security/page/4/'] : page 3 should not have been fetched
```

Page 4, not page 5, is where it stops even at `max_pages=5`: only three pages are prepared, so page 4 is link-free and ends the walk there.

- [ ] **Step 3: Write the implementation**

In `web/lib/scraper.py`, give `get_links` the stop rule:

```python
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
```

`all(...)` over an empty `fresh` is `True`, which is what we want: a page that repeats only links we already have ends the walk.

- [ ] **Step 4: Run the tests to verify they pass**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
.venv\Scripts\python.exe web\tests\test_scraper_retry.py
```

Expected: 8 tests `OK`, then 3 tests `OK`.

- [ ] **Step 5: Pass the callable from the ingester**

In `web/lib/ingest.py`, change the import on line 8:

```python
from .scraper import MAX_PAGES, SITES, get_links, get_sitemap_entries, scrape_article
```

Change `ingest_site`'s signature and its `get_links` call (`web/lib/ingest.py:17` and `:31-36`):

```python
def ingest_site(source, max_pages=MAX_PAGES, stop_at_known=True):
    """Scrape one site. Opens its own connection so sites can run in parallel.

    `stop_at_known` lets the walk end as soon as a section page holds nothing
    new, which is what the daily cron wants. backfill.py turns it off so a deep
    walk reaches old articles even when the recent pages are fully stored."""
    result = {"source": source, "links_found": 0, "new_articles": 0, "failed": 0, "title_only": 0, "error": None}
    conn = db.connect()
```

```python
        try:
            links = get_links(
                source,
                known=(lambda urls: db.existing_urls(conn, urls)) if stop_at_known else None,
                max_pages=max_pages,
            )
        except Exception as e:
            links = []
            if not sitemap:
                errors.append(_err("category page", e))
```

Change `run_ingest` (`web/lib/ingest.py:68-74`):

```python
def run_ingest(sources=None, max_pages=MAX_PAGES, stop_at_known=True):
    sources = sources or list(SITES)
    # Make sure the schema exists once before the parallel workers race to create it.
    db.connect().close()
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        results = list(pool.map(lambda s: ingest_site(s, max_pages, stop_at_known), sources))
    return {"new_articles": sum(r["new_articles"] for r in results), "sites": results}
```

`conn` is created and used in the same thread as the walk, so the closure is safe; the `ThreadPoolExecutor` below it only fetches articles.

- [ ] **Step 6: Check the callers still type-check and import**

```powershell
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'web'); import lib.ingest, api.cron; print('imports ok')"
```

Expected: `imports ok`. `api/cron.py` calls `run_ingest(SERVER_SOURCES)` and `run_local.py` calls `run_ingest(sys.argv[1:] or None)` — both pass only the first argument, so neither file changes.

- [ ] **Step 7: Smoke-test against the real database**

This one writes: it inserts an `ingest_runs` row per site, and any article it finds that is missing. Needs `DATABASE_URL`, which `run_local.py` reads from `web/.env`. Start with Ynet, which has no `page_url` and is already 100% stored, so a healthy run reports `links_found: 40`-ish and `new_articles: 0`:

```powershell
.venv\Scripts\python.exe web\run_local.py Ynet
```

Expected: JSON with `"links_found"` nonzero, `"new_articles": 0`, `"error": null`. Then one paginated site, where `links_found` should now exceed a single page (Channel 13 was ~32 before):

```powershell
.venv\Scripts\python.exe web\run_local.py "Channel 13"
```

Both scripts resolve `web/` and `web/.env` from their own `__file__`, so the working directory does not matter.

Expected: `links_found` above ~32 and `new_articles` above 0 — the walk reached material the database lacks. `"error": null`.

- [ ] **Step 8: Commit**

```bash
git add web/lib/scraper.py web/lib/ingest.py web/tests/test_scraper_pagination.py
git commit -m "Stop the section walk once a page holds nothing new

The walk ends before page N+1 when every link on page N was already
seen in the walk or is already stored, so in steady state it costs one
or two extra category fetches and after an outage it walks deeper by
itself. The database arrives as an injected callable, so scraper.py
still imports nothing from db.py.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The one-time deep backfill, and the README

The first deep walk cannot run on Vercel: i24's share alone is ~88 articles at 15-20 s each on a cold cache, roughly 7 minutes with 4 workers, against a 300 s ceiling. It runs once from a developer machine instead.

The script reuses `run_ingest` rather than reimplementing the scrape-and-insert loop, so it inherits `existing_urls` skipping, the dedup rules, `ingest_runs` logging and the retry window. It passes `stop_at_known=False`: the recent pages of each section are likely fully stored, and the adaptive rule would stop the walk at page 1 before it ever reached the gap.

**Files:**
- Create: `web/backfill.py`
- Modify: `web/README.md`

**Interfaces:**
- Consumes: `run_ingest(sources=None, max_pages=MAX_PAGES, stop_at_known=True)` from Task 4; `load_env()` from `web/import_csv.py:50`.
- Produces: a CLI, nothing importable by the deployed code. Only `api/*.py` become Vercel functions (`web/vercel.json`), so `backfill.py` ships as an inert file beside `run_local.py` and `import_csv.py`.

- [ ] **Step 1: Write the script**

Create `web/backfill.py`:

```python
"""
One-time deep walk of every site's section, to collect the articles that were
never ingested because the scraper only read page 1. Run locally - it takes
far longer than Vercel's 300 s function ceiling.

    python backfill.py --dry-run             # show the plan, write nothing
    python backfill.py                       # all sites, 25 pages each
    python backfill.py "Channel 13" "I24 NEWS"
    python backfill.py --max-pages 10

25 pages reaches roughly 4-5 months back, at the measured 5-6 days per page.
Sites without a `page_url` (Ynet, Channel 14, Kan News) read one page however
deep the cap, because their sections do not paginate.

Unlike the daily cron this does not stop when a page is fully stored: the
recent pages are, and the gap is behind them. Articles already in the database
are still skipped, so running it twice is safe. Needs DATABASE_URL, read from
web/.env if present.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from import_csv import load_env  # noqa: E402
from lib.ingest import run_ingest  # noqa: E402
from lib.scraper import SITES  # noqa: E402

BACKFILL_PAGES = 25


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*", help="site names; default all of them")
    ap.add_argument("--max-pages", type=int, default=BACKFILL_PAGES,
                    help=f"section pages to walk per site (default {BACKFILL_PAGES})")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be walked and exit")
    args = ap.parse_args()

    sources = args.sources or list(SITES)
    unknown = [s for s in sources if s not in SITES]
    if unknown:
        ap.error(f"unknown site(s): {', '.join(unknown)}. Known: {', '.join(SITES)}")

    for s in sources:
        pages = args.max_pages if SITES[s].get("page_url") else 1
        print(f"{s}: {pages} page(s)")
    if args.dry_run:
        print("dry run: nothing written")
        return

    load_env()
    print(f"walking {len(sources)} site(s), up to {args.max_pages} pages each; "
          f"this takes many minutes", flush=True)
    print(json.dumps(run_ingest(sources, max_pages=args.max_pages, stop_at_known=False),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

`load_env()` is called only after the dry-run exit, so `--dry-run` works without `DATABASE_URL`.

- [ ] **Step 2: Verify the dry run, with no database involved**

```powershell
.venv\Scripts\python.exe web\backfill.py --dry-run
```

Expected, in `SITES` order:

```
Ynet: 1 page(s)
Kan News: 1 page(s)
Channel 13: 25 page(s)
Channel 14: 1 page(s)
I24 NEWS: 25 page(s)
Channel 12: 25 page(s)
dry run: nothing written
```

The three paginated sites at 25, the other three at 1. Then check the argument guard:

```powershell
.venv\Scripts\python.exe web\backfill.py "Channel 99" --dry-run
```

Expected: exit code 2 and `backfill.py: error: unknown site(s): Channel 99. Known: Ynet, Kan News, ...`.

- [ ] **Step 3: Update the README**

In `web/README.md`, extend the site table's header and the three paginated rows:

```markdown
| Site | Category page | Pages walked |
|---|---|---|
| Ynet | ynet.co.il/news/category/344 | 1 (no pagination) |
| Kan News | kan.org.il/content/kan-news/defense/ | 1 (no pagination) |
| Channel 13 | 13tv.co.il/news/politics/security/ | up to `MAX_PAGES` |
| Channel 14 | c14.co.il/archive/990 | 1 (no pagination) |
| I24 NEWS | i24news.tv/he/news/news/defense-news | up to `MAX_PAGES` |
| Channel 12 | mako.co.il/news-military | up to `MAX_PAGES` |
```

In "How it works", replace the `lib/ingest.py` bullet and add one about the walk:

```markdown
- `lib/scraper.py`: plain HTTP scrapers (no browser). `curl_cffi` imitates Chrome,
  which gets past Channel 13's and Mako's bot checks. Title, body and publish date
  come from each article's schema.org `NewsArticle` data.
- Three sections paginate (Channel 13, Channel 12, i24), so `get_links` walks them
  page by page, up to `MAX_PAGES` (3, about 15-18 days of history). It stops early
  once a page holds nothing that is not already stored, so a normal run costs one
  or two extra page fetches and a run after an outage walks deeper by itself.
  Ynet and Channel 14 return page 1 for `?page=2`; they read one page.
- `lib/ingest.py`: for each site (all in parallel): walk the section pages, skip
  URLs already in the DB, scrape the rest, insert them, log the run.
```

In "Local tools", add the backfill:

```markdown
- `python backfill.py --dry-run`: show how deep a backfill would walk, write nothing.
- `python backfill.py`: one-time deep walk (25 pages, ~4-5 months) to collect
  articles from before the project started or from days when a run failed. Takes
  many minutes, which is why it is not a Vercel function. Safe to re-run.
```

- [ ] **Step 4: Verify the README renders and says what changed**

```powershell
git diff web/README.md
```

Expected: the table gains a third column, the "How it works" list gains the pagination bullet, "Local tools" gains two `backfill.py` lines. No other lines touched.

- [ ] **Step 5: Commit**

```bash
git add web/backfill.py web/README.md
git commit -m "Add the one-time deep backfill script

backfill.py walks 25 section pages per site - about 4-5 months - and
reuses run_ingest so it inherits the dedup, the retry window and the
ingest_runs logging. It turns the adaptive stop rule off, because the
recent pages are already stored and the gap is behind them. Too slow
for a Vercel function, so it is run locally once.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Deploy, backfill, verify

Everything so far is local. This task makes it live and confirms the 245 arrive. It is the only task that needs the user's go-ahead: step 2 pushes to `origin/main`, which triggers a Vercel production deploy.

**Files:** none

**Interfaces:**
- Consumes: Tasks 1-5, all committed.
- Produces: nothing in code. The measured outcome — the missing section articles in the `articles` table, and a healthy next cron run.

- [ ] **Step 1: Run the whole suite one more time**

```powershell
.venv\Scripts\python.exe web\tests\test_scraper_retry.py
.venv\Scripts\python.exe web\tests\test_scraper_pagination.py
```

Expected: 3 tests `OK`, then 8 tests `OK`. Do not continue on a failure.

- [ ] **Step 2: Ask, then push**

Ask the user before pushing — it deploys to production. On their go-ahead:

```bash
git push origin main
```

Then watch the Vercel dashboard for the deployment to finish, and load the site to confirm it still serves.

- [ ] **Step 3: Record the "before" count**

The dashboard's per-site totals are the baseline for step 5. Open https://news-semantic-model.vercel.app/ (the user signs in; the password is theirs to enter, not Claude's) and note each site's **Total**, or read it from the API in the browser's own session at `/api/stats?days=0`.

- [ ] **Step 4: Run the backfill locally**

Expect many minutes: i24's share alone is ~88 articles at 15-20 s each on a cold cache, about 7 minutes with 4 workers, and the three paginated sites run in parallel. Run it in a terminal the user can watch rather than in the background.

```powershell
.venv\Scripts\python.exe web\backfill.py "Channel 13" "I24 NEWS" "Channel 12"
```

Expected: JSON with, across the three sites, `new_articles` summing to roughly 245 or more (six pages were measured; 25 pages reach further back), `links_found` in the hundreds per site, `error: null`, and a low `failed` count. A large `failed` on i24 means the retry window is not holding — stop and investigate before re-running.

- [ ] **Step 5: Confirm the articles landed**

Reload the dashboard. Expected: the three sites' **Total** up by the `new_articles` the script reported; the per-day chart grouped by publish date showing a spread back over months, not a single spike on today; "Latest articles" unchanged, since backfilled articles are older than what is already there.

- [ ] **Step 6: Check the next cron run**

The cron runs at 20:00 UTC (`web/vercel.json`). The day after, on the dashboard's health panel, expected: `links_found` for Channel 13, Channel 12 and i24 higher than before this work (two pages' worth rather than one), `new_articles` back to the usual handful now that the history is in, and no new error. `links_found` staying at its old single-page value for one of the three means that site's `page_url` has stopped working — the quiet failure the spec warns about.

---

## Deferred

Found while planning, deliberately not in this plan:

- **Per-site `links_found` trends on the dashboard.** The spec names this as a follow-up: a site whose pagination scheme changes degrades silently to page 1, and nothing surfaces it. Step 6 above catches it once, by hand.
- **A `degraded` health state.** I24 reads "✓ OK" while failing half its runs, because the status only asks whether there was a success in the last 26 h. Offered earlier, not taken up.
- **`web/README.md`'s timezone line** says 20:00 UTC is "23:00 Israel winter time, 22:00 summer"; it is the other way round. Unrelated to pagination.
- **Channel 13's 43% publish-date coverage** and **Ynet's RSS feed returning no pattern matches.** Both noted during the ingestion audit, neither touched here.
