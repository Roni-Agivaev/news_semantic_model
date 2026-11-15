# Politics Pipeline and New Outlets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Scrape political news into a `political_articles` table with the existing scraper code.
- Add Maariv, Israel Hayom, JDN, Zman Israel and Davar to the defense pipeline.

**Architecture:**
- `SITES` becomes topic → source → config, with a list of sections per source.
- Every layer takes a `topic`: ingest, db, cron, backfill, API.
- `db.TABLES` maps a topic to its table. Both article tables share one shape, so the same SQL serves both.

**Tech Stack:**
- Python 3.12, curl_cffi and BeautifulSoup, psycopg 3 on Supabase Postgres.
- Vercel Python functions and Vercel Cron, plus a GitHub Action for Kan.
- Vanilla JS dashboard.
- Tests use stdlib `unittest`, offline.

Spec: `docs/superpowers/specs/2026-11-15-politics-pipeline-design.md`.

## Global Constraints

**Topics:**
- Topics are exactly `("defense", "politics")`.
- A topic never reaches SQL as text. It goes through `db.table_for(topic)`, which raises `ValueError` for anything else.
- Sections are `defense`, `domestic`, `diplomatic` or `combined`.

**Storage:**
- `articles` gains `section TEXT NOT NULL DEFAULT 'defense'`.
- `political_articles` has the same columns, with `section TEXT NOT NULL`.
- `ingest_runs` and `scrape_runs` gain `topic TEXT NOT NULL DEFAULT 'defense'`.

**Behaviour that must not change:** the 6 existing defense outlets keep today's
URLs, link patterns, pagination, retry windows and sitemap use.

**Tests:**
- Run from `web/` with `../.venv/Scripts/python.exe tests/<file>.py`.
- Every test file must print `OK`.
- No test touches the network or the database.

**Safety:**
- Never run anything that connects to `DATABASE_URL` without the user's OK. `db.connect()` applies the schema migration to production.
- Never push.
- Commit on branch `politics-pipeline`. Messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never commit `.claude/` or `pilot/`.

**Labels:**
- The sidebar labels are "Defense", "Politics" and "Logs".
- The politics filter control reads All / Domestic / Diplomatic.

---

## File map

| File | Change |
|---|---|
| `web/lib/scraper.py` | `TOPICS`; `SITES[topic][source]` with `sections`; `sources(topic)`, `server_sources(topic)`; `get_links(topic, source, ...)` → `[(url, section)]`; RSS sections; `get_sitemap_entries(topic, source)` adds `section`; Kan boilerplate stripping |
| `web/lib/db.py` | schema additions; `TABLES`, `table_for(topic)`; `topic` on `existing_urls`, `insert_articles`, `log_run`, `start_scrape_run`, `stats`, `search_articles`, `list_scrape_runs` |
| `web/lib/events.py` | `RunLog(..., topic=)` passes the topic to `start_run` |
| `web/lib/ingest.py` | `ingest_site(topic, source, ...)`, `run_ingest(topic, sources, ..., since=None)` |
| `web/api/cron.py` | `?topic=` (GET and POST) |
| `web/api/stats.py`, `web/api/articles.py` | `?topic=`, `?section=`; unknown topic → 400 |
| `web/api/logs.py` | runs carry `topic` |
| `web/run_local.py`, `web/backfill.py` | `--topic`; backfill `--days` |
| `web/vercel.json` | two crons; `/politics` rewrite |
| `web/dev_server.py` | `/politics` route |
| `.github/workflows/kan-daily.yml` | both topics |
| `web/public/*` | topic-aware dashboard, sidebar, section filter, logs topic, 11 site colors |
| `web/clean_kan.py` | one-off Kan cleanup (run only with the user's OK) |
| tests | migrate four existing files; new `test_sections.py`, `test_topics_db.py`, `test_kan_clean.py`, `test_backfill_since.py` |

---

### Task 1: Topic-keyed registry with sections

**Files:**
- Modify: `web/lib/scraper.py`
- Modify tests: `web/tests/test_scraper_pagination.py`, `test_scraper_events.py`, `test_scraper_retry.py`
- Create: `web/tests/test_sections.py`

**Interfaces (produces):**
- `TOPICS = ("defense", "politics")`
- `SITES[topic][source] = {"base": str, "sections": [section, ...], "sitemap_url"?: str, "server_blocked"?: bool}`
- A section is `{"name": str, "category_url": str, "link_pattern": str, "page_url"?: str, "rss_url"?: str}`
- `sources(topic) -> list[str]`
- `server_sources(topic) -> list[str]`
- `get_links(topic, source, schedule=SECTION_RETRY_AT_S, known=None, max_pages=MAX_PAGES, log=None) -> list[tuple[str, str]]`
  - returns `(url, section_name)` pairs, de-duplicated by URL;
  - the first section to list a URL wins.
- `get_sitemap_entries(topic, source) -> {url: {"title", "published_at", "section"}}`
  - only URLs matching one of the topic's section patterns;
  - `section` is the first section whose pattern matches.

**How it works:**
- The current `get_links` body becomes `_walk_section(section, base, schedule, known, max_pages, log) -> list[str]`, unchanged except that it reads `section` and `base`.
  - `base` is copied into a dict passed to `_links_on_page`/`_fetch_links` as `{**section, "base": base}`.
- **Failures:** a section whose page 1 fails is raised only if it is the source's **only** section. Otherwise it is logged as `warn` (`"Section {name} failed: ..."`) and the other sections continue. If every section fails, the last error is raised.
- **Log messages:** with more than one section, each section's messages are prefixed `"[{name}] "` so the logs show which section a page belongs to.
- **Defense entries:** the 6 existing ones move verbatim into `SITES["defense"]`, each with one section named `defense`.
- **Tests:** existing tests are migrated to `scraper.get_links("defense", SOURCE, ...)`, comparing URLs (`[u for u, _ in links]`). Tests that patch `scraper.SITES` patch `scraper.SITES["defense"]`.

- [ ] Step 1: write `test_sections.py`:
  - two sections → tagged pairs, de-duplicated;
  - one failing section of two → the other's links plus a `warn` event;
  - all sections failing → raises;
  - `sources()` / `server_sources()` (Kan is excluded from the server sources);
  - sitemap entries carry `section` and drop non-matching URLs.

  Run it and see it fail.
- [ ] Step 2: migrate the existing tests to the new call shape. Run them and see them fail.
- [ ] Step 3: implement the registry and `get_links`. Run all tests; they pass.
- [ ] Step 4: commit with the message "Key the site registry by topic and section".

### Task 2: RSS sections (Ynet politics)

**Files:**
- Modify: `web/lib/scraper.py`
- Test: `web/tests/test_sections.py`

**Interfaces:** `_links_from_rss(xml, section, base) -> list[str]`.
- It reads `<link>` and `<guid>` values, unwrapping CDATA.
- It keeps the values that `re.fullmatch(re.escape(base) + link_pattern)`, in feed order, de-duplicated.
- A section with `rss_url` is fetched once (no pagination, no shell retries) and logged as `"Feed: {n} links, {new} not stored yet"`.

- [ ] Step 1: add a failing test with an inline RSS sample. It has a channel link, two article links (one with CDATA) and a foreign link; the expected result is the two article URLs.
- [ ] Step 2: implement and pass.
- [ ] Step 3: commit with the message "Read article links from RSS sections".

### Task 3: New outlets and politics sections

**Files:**
- Modify: `web/lib/scraper.py`
- Test: `web/tests/test_sections.py`

The values are copied from the spec tables:

- **Defense, added:** Maariv, Israel Hayom, JDN, Zman Israel, Davar.
- **Politics:**
  - Ynet (RSS 185, combined)
  - Kan News (combined, `server_blocked`, `sitemap_url`)
  - Channel 12 (domestic, diplomatic)
  - Channel 13 (domestic, diplomatic)
  - Channel 14 (combined, `archive/65839`)
  - I24 NEWS (combined)
  - Maariv (combined)
  - Israel Hayom (domestic, diplomatic `geopolitics`)
  - JDN (domestic, diplomatic `category/news/state/`)
  - Zman Israel (combined)

**Patterns:**
- Channel 12 politics: `r"/news-politics/[A-Za-z0-9_/\-]*Article-[A-Za-z0-9]+\.htm"`, and the same with `news-diplomatic`.
- Channel 13: `r"/item/news/politics/politics/[A-Za-z0-9\-]+/?"`, and the same with `state-policy`.
- Channel 14 politics uses the same `/article/\d+` pattern as defense.
- **Absolute-URL patterns** (JDN, Zman, Davar) match the full URL. `_links_on_page` already keeps a match that does not start with `/`.
- **Exclusive patterns:** JDN and Zman links carry no section in the URL, so a section's pattern is only applied to that section's page.

**Test:** for every section, a synthetic HTML or RSS snippet holding:
- one real-shaped article link (taken from the live probe in the spec);
- one link from another section of the same outlet, which must not match when the patterns differ by path.

`get_links` on the snippet must return the expected URL with the right section name.

- [ ] Step 1: write the parametrised failing test.
- [ ] Step 2: add the config and pass.
- [ ] Step 3: commit with the message "Add politics sections and five new defense outlets".

### Task 4: Strip Kan page boilerplate

**Files:**
- Modify: `web/lib/scraper.py` (`parse_article`)
- Create: `web/clean_kan.py`, `web/tests/test_kan_clean.py`

**Interfaces:** `strip_boilerplate(text) -> str`.
- It removes every `"התחברו וקבלו תוכן מותאם אישית"`.
- It removes a trailing `"Website created by IdeoDigital"` and anything after it.
- It collapses runs of spaces and strips the result.
- `parse_article` applies it to the content.

**`clean_kan.py`:**
- Selects rows in both tables whose content contains either phrase, and updates them with `strip_boilerplate`.
- `--dry-run` prints counts only.
- It connects to the database, so it runs only with the user's OK.

- [ ] Step 1: failing tests: both phrases are removed; text without them is unchanged; the four-times prefix is fully removed.
- [ ] Step 2: implement and pass.
- [ ] Step 3: commit with the message "Strip Kan sign-in and footer boilerplate from article text".

### Task 5: Topic-aware storage

**Files:**
- Modify: `web/lib/db.py`, `web/lib/events.py`
- Create: `web/tests/test_topics_db.py`

**Interfaces:**
- `TABLES = {"defense": "articles", "politics": "political_articles"}`
- `table_for(topic) -> str`; raises `ValueError`.
- `existing_urls(conn, urls, topic="defense")`
- `insert_articles(conn, articles, origin="scraper", topic="defense")`. Each article dict may carry `section`; the default is the topic's default section: `"defense"` for defense, `"combined"` for politics.
- `log_run(conn, source, ..., run_id=None, topic="defense")`
- `start_scrape_run(conn, run_id, trigger, sources, topic="defense")`
- `stats(conn, by, days, coverage_days, topic="defense", section="")`
- `search_articles(conn, ..., topic="defense", section="")`
- `RunLog(trigger, sources, writer, ..., topic="defense")`. `DbWriter.start_run(run_id, trigger, sources, topic)`.
- `list_scrape_runs` and `get_scrape_run` return `topic`.

**Schema** (appended to `SCHEMA`):
- `ALTER TABLE articles ADD COLUMN IF NOT EXISTS section TEXT NOT NULL DEFAULT 'defense';`
- `CREATE TABLE IF NOT EXISTS political_articles (...)`, with the same columns as `articles` plus `section TEXT NOT NULL DEFAULT 'combined'`, and its own indexes:
  - `political_articles_source_title` unique;
  - `published_at`;
  - `ingested_at`;
  - `section`.
- `ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS topic TEXT NOT NULL DEFAULT 'defense';` and the same for `scrape_runs`.
- `ALTER TABLE political_articles ENABLE ROW LEVEL SECURITY;`

**`SCHEMA_CHECK`:**
- 5 tables with RLS;
- the `ingest_runs` columns `title_only`, `run_id` and `topic`;
- `articles.section`.

**SQL:**
- Every `FROM articles` / `INTO articles` / `UPDATE articles` uses `{table}` from `table_for(topic)`, through an f-string over the whitelisted name.
- `ingest_runs` reads in `stats` filter `WHERE topic = %(topic)s`.
- Article reads in `stats` and `search_articles` filter `(%(section)s = '' OR section = %(section)s)`.

**Tests** (no database, using a fake connection that records `execute` calls):
- `table_for`: both topics map correctly, and an unknown topic raises;
- `insert_articles` with topic politics writes to `political_articles` with the section;
- `stats` SQL for politics reads `political_articles` and never `FROM articles`;
- `SCHEMA` contains the new DDL, and `SCHEMA_CHECK` counts 5 RLS tables;
- `RunLog` passes the topic to `start_run`.

The existing `test_schema_setup.py` and `test_events.py` must still pass, with their fakes updated to the new arity.

- [ ] Step 1: write the failing tests and update the fakes.
- [ ] Step 2: implement and pass.
- [ ] Step 3: commit with the message "Store politics in its own table; tag runs with a topic".

### Task 6: Topic-aware ingest

**Files:**
- Modify: `web/lib/ingest.py`
- Modify test: `web/tests/test_ingest_events.py`

**Interfaces:**
- `ingest_site(topic, source, max_pages=MAX_PAGES, stop_at_known=True, log=null_log, run_id=None, since=None)`
- `run_ingest(topic, sources=None, max_pages=MAX_PAGES, stop_at_known=True, trigger="manual", since=None)`
  - `sources=None` means `sources(topic)`;
  - unknown sources raise `ValueError`;
  - the result is `{"run_id", "topic", "new_articles", "sites"}`.
- `ingest_site` does the following:
  - keeps a `section_of = {url: section}` map from `get_links` and the sitemap;
  - sets `article["section"]`;
  - passes `topic` to the db calls;
  - with `since` (an aware datetime), drops scraped articles whose `published_at` is older, and logs `"Skipped N older than {date}"`.

- [ ] Step 1: update `test_ingest_events.py`:
  - the fakes take the new signatures;
  - inserted articles carry their section;
  - add a `since` test where 1 of 2 scraped articles is too old, so 1 is inserted and a skip event is logged.

  Run it and see it fail.
- [ ] Step 2: implement and pass.
- [ ] Step 3: commit with the message "Thread the topic through ingest; add a since cutoff".

### Task 7: Entry points and schedules

**Files:**
- Modify: `web/api/cron.py`, `web/run_local.py`, `web/backfill.py`, `web/vercel.json`, `.github/workflows/kan-daily.yml`
- Create: `web/tests/test_backfill_since.py`

**Changes:**
- **cron.py:**
  - `topic = query topic or "defense"`; an unknown topic → 400;
  - it calls `run_ingest(topic, server_sources(topic), trigger=...)`;
  - POST (Ingest now) runs **both** topics in sequence and returns `{"runs": [defense_result, politics_result], "kan": ...}`.
- **run_local.py:** `--topic` (default from `RUN_TOPIC`, else `defense`); positional sources.
- **backfill.py:**
  - `--topic` (default `defense`) and `--days` (default 90, 0 = no cutoff);
  - `since = now - days`, passed to `run_ingest`;
  - the dry run prints, per source and section, the pages it would walk.
- **vercel.json:**
  - crons `/api/cron?topic=defense` at `0 20 * * *` and `/api/cron?topic=politics` at `30 20 * * *`;
  - rewrite `{ "source": "/politics", "destination": "/index.html" }`.
- **kan-daily.yml:**
  - two steps: `python run_local.py --topic defense "Kan News"`, then `--topic politics "Kan News"`;
  - each fails the job only if its site errored.
- **test_backfill_since.py:** `backfill.build_args([...])` returns `(topic, sources, max_pages, since)`.
  - an unknown topic or source is an error;
  - `--days 0` gives `since=None`.

  The CLI parsing is factored into `build_args` so it can be tested.

- [ ] Step 1: write the failing test.
- [ ] Step 2: implement all entry points and pass.
- [ ] Step 3: commit with the message "Run each topic from cron, local runs, backfill and the Kan action".

### Task 8: API and dashboard

**Files:**
- Modify: `web/api/stats.py`, `web/api/articles.py`, `web/api/logs.py`, `web/dev_server.py`
- Modify: `web/public/index.html`, `app.js`, `app.css`, `logs.html`, `logs.js`

**API:**
- `stats` and `articles` read `topic` (default `defense`; other values → 400) and `section`.
- `section` is whitelisted to `domestic`, `diplomatic` or `combined`. Anything else, or the defense topic, gives `""`.

**dev_server.py:** rewrites `/politics` to `/index.html`.

**app.js:**
- `TOPIC = location.pathname.startsWith("/politics") ? "politics" : "defense"`, added to every `/api/stats` and `/api/articles` call.
- The page title becomes "Politics" or "Defense", and the subtitle `${sites.length} news sites · politics sections` or `· defense sections`.
- For politics only, a `seg` control `#section` (All / Domestic / Diplomatic) sets `state.section`, which is passed to both APIs.
- Ingest now shows both topics' results.

**SOURCES (site colors):** the order becomes

`["Ynet", "Kan News", "Channel 13", "Channel 14", "I24 NEWS", "Channel 12", "Maariv", "Israel Hayom", "JDN", "Zman Israel", "Davar"]`

- `app.css` gains `--s7`…`--s11` in all three theme blocks:
  - light: `#7b5cd6 #c2410c #0e7490 #a16207 #be185d`
  - dark: `#9b80ea #e0682f #22a3c3 #caa03a #e2559a`
- `logs.js` uses the same `SOURCES` list.

**Sidebar** (both HTML files): Defense `/`, Politics `/politics`, Logs `/logs`. `nav.js` marks the current page by path.

**Logs:**
- `logs.js` shows a topic badge on each run.
- A Topic select (All / Defense / Politics) filters the run list client-side.

**Verify** in the local preview against `dev_server.py`. Starting it connects to the database, so it needs the user's OK first.

- [ ] Step 1: implement the API and run the existing tests.
- [ ] Step 2: implement the front end.
- [ ] Step 3: verify in the preview (after the user's OK).
- [ ] Step 4: commit with the message "Politics dashboard page, topic filters and new site colors".

### Task 9: Live check of every section (network, no database)

**Files:** create `web/check_sections.py`.

- For each topic, source and section, it calls `get_links` with `known=None, max_pages=1`.
- It parses the first link with `scrape_article`.
- It prints the link count, the title and the character count.
- It exits non-zero if any section returns 0 links.

- [ ] Step 1: run it. Fix any pattern that returns 0 links, including the two sections the spec marks "not yet probed".
- [ ] Step 2: commit with the message "Add a live section check script".

### After the plan (user's OK required)

These touch production:

1. Push the branch and merge, which deploys. The first connection migrates the schema.
2. `python clean_kan.py`
3. `python backfill.py --topic politics`
4. `python backfill.py --topic defense Maariv "Israel Hayom" JDN "Zman Israel" Davar`
5. Watch the first two crons on /logs. Any outlet blocked from Vercel gets `server_blocked: True` and joins the Kan action.
