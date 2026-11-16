# Politics pipeline and new outlets: design

Date: 2026-11-15. Status: implemented.

> **Update 2026-11-16:** Zman Israel and Davar were removed from both topics.
> Their Cloudflare began answering 403 with a bot check to the local backfill
> and to the Vercel crons. Their old run rows are kept, and the dashboard lists
> only the sources still in the registry.

## Goal

1. Scrape political news from the same outlets as the defense pipeline, plus
   new ones, into a **separate table**, using the **same scraper code**.
2. Add the new outlets to the **defense** pipeline too.
3. Backfill about **90 days** of history for every new section.

## Outlets and sections

Checked live on 2026-11-15: each section page was fetched with curl_cffi, and two
articles from it were parsed with `parse_article`.

### Defense (`articles` table)

The 6 existing outlets stay as they are. New ones:

| Outlet | Section page | Article links | Page 2 |
|---|---|---|---|
| Maariv | `https://www.maariv.co.il/news/military` | `/news/military/article-\d+` | none (`?page=2` repeats page 1) |
| Israel Hayom | `https://www.israelhayom.co.il/news/defense` | `/news/defense/article/\d+` | `/news/defense/page/{n}` |
| JDN | `https://www.jdn.co.il/category/news/military/` | `https://www.jdn.co.il/news/\d+/` | `/category/news/military/page/{n}/` |
| Zman Israel | `https://www.zman.co.il/feed/561/` | `https://www.zman.co.il/\d{6}/` | `/feed/561/page/{n}/` |
| Davar | `https://www.davar1.co.il/topic/צבא-וביטחון/` (URL-encoded) | `https://www.davar1.co.il/\d{6}/` | none found |

### Politics (`political_articles` table)

`section` is `domestic`, `diplomatic` or `combined` (the outlet's section mixes both).

| Outlet | Section | Source | Article links |
|---|---|---|---|
| Ynet | combined | RSS `https://www.ynet.co.il/Integration/StoryRss185.xml` | `/news/article/[A-Za-z0-9]+` |
| Kan News | combined | `https://www.kan.org.il/content/kan-news/politic/`, `?page={n}` | `/content/kan-news/politic/\d+/?` |
| Channel 12 | domestic | `https://www.mako.co.il/news-politics`, `?page={n}` | `/news-politics/...Article-[A-Za-z0-9]+\.htm` |
| Channel 12 | diplomatic | `https://www.mako.co.il/news-diplomatic`, `?page={n}` | `/news-diplomatic/...Article-...\.htm` |
| Channel 13 | domestic | `https://13tv.co.il/news/politics/politics/`, `page/{n}/` | `/item/news/politics/politics/[A-Za-z0-9\-]+/?` |
| Channel 13 | diplomatic | `https://13tv.co.il/news/politics/state-policy/`, `page/{n}/` | `/item/news/politics/state-policy/[A-Za-z0-9\-]+/?` |
| Channel 14 | combined | `https://www.c14.co.il/archive/65839` | `/article/\d+` |
| I24 NEWS | combined | `https://www.i24news.tv/he/news/news/politics` | `/he/news/news/politics/artc-[A-Za-z0-9]+` |
| Maariv | combined | `https://www.maariv.co.il/news/politics` | `/news/politics/article-\d+` |
| Israel Hayom | domestic | `https://www.israelhayom.co.il/news/politics`, `/page/{n}` | `/news/politics/article/\d+` |
| Israel Hayom | diplomatic | `https://www.israelhayom.co.il/news/geopolitics` | `/news/geopolitics/article/\d+` *(not yet probed)* |
| JDN | domestic | `https://www.jdn.co.il/category/news/politics/`, `page/{n}/` | `https://www.jdn.co.il/news/\d+/` |
| JDN | diplomatic | `https://www.jdn.co.il/category/news/state/` | same *(not yet probed)* |
| Zman Israel | combined | `https://www.zman.co.il/feed/609/`, `page/{n}/` | `https://www.zman.co.il/\d{6}/` |

Davar has no politics section, only an elections tag, so it is defense only.

**Ynet** needs RSS: without JavaScript its politics category page shows the
defense list. Its RSS feed also carries some defense items, because Ynet files
articles under several categories. That is accepted (see Overlap below).

**Excluded, with the reason:**
- **Walla:** section pages are rendered by JavaScript, and its RSS feeds looked weeks stale.
- **Srugim:** only 8 links per section page.
- **Haaretz:** paywall, about 500 characters per article.
- **Makor Rishon:** returns a 20 KB shell.

Walla and Srugim can be revisited as a separate task.

**Overlap:** an article listed in both a defense and a politics section is
stored in both tables, deliberately. Within a table, `url` stays unique, and
`(source, title)` stays unique as it is now.

## Architecture

### Site registry (`web/lib/scraper.py`)

`SITES` becomes topic → source → config:

- A source holds a list of **sections**. Each section has:
  - `name` (`domestic`, `diplomatic`, `combined`, or `defense`)
  - `category_url`
  - `link_pattern`
  - optional `page_url`
  - optional `rss_url`
- Source-level keys stay where they are: `base`, `sitemap_url`, `server_blocked`.
- `TOPICS = ("defense", "politics")`.

`get_links(topic, source, ...)` walks every section of the source:

- It returns `(url, section)` pairs, de-duplicated by URL. The first section that lists a URL wins.
- A section with `rss_url` reads `<link>` items from the feed instead of walking pages. Links are still filtered by `link_pattern`.
- Pagination, cold-cache retries and stop-at-known work as now, per section.

Existing tests are migrated to the new shape. The defense behaviour of the 6
current outlets must not change.

### Storage (`web/lib/db.py`)

- New table `political_articles`:
  - the same columns and indexes as `articles`, plus `section TEXT NOT NULL`;
  - RLS enabled, like the other tables;
  - added to `SCHEMA` and `SCHEMA_CHECK`.
- Article functions (insert, existing-URL lookup, stats, explorer queries) take
  a `topic` and choose the table through one mapping
  `{"defense": "articles", "politics": "political_articles"}`.
  - A topic string never goes into SQL directly.
  - Unknown topics raise.
- `ingest_runs`, `scrape_runs` and `ingest_events` get `topic TEXT NOT NULL DEFAULT 'defense'`.
  Existing rows become defense automatically.

### Runs

- **Cron:** `api/cron.py` takes `?topic=`, default `defense`. In `vercel.json`:
  - `/api/cron?topic=defense` at `0 20 * * *` (the existing cron);
  - `/api/cron?topic=politics` at `30 20 * * *`.

  Each gets the 300 s limit. That makes two crons, the Hobby-plan maximum.
- **Ingest:** `run_ingest(topic, sources, ...)` and `ingest_site(topic, source, ...)`
  pass the topic down. The per-source thread pool is unchanged.
- **Local and Kan runs:** `run_local.py` takes `--topic` (or `RUN_TOPIC`). The Kan
  GitHub Action runs both topics one after the other.
- **Sites that block Vercel:** this is unknown for the new outlets until the first
  cron runs. The logs page shows it. A blocked outlet gets `server_blocked: True`
  and moves to the GitHub Action, as Kan did.

### Backfill (`web/backfill.py`)

- New options:
  - `--topic`;
  - `--days 90`: articles published before the cutoff are dropped before they are stored.
- Section pages carry no dates, so the walk itself is still bounded by the page cap.
- **Sections without pagination** (Maariv, Davar, I24, Channel 14, Ynet RSS) only
  backfill what their first page lists. A deeper backfill for those, via sitemaps,
  is out of scope.
- **One-off runs, after deploy:**
  - politics: all sources;
  - defense: the 5 new outlets.

### Dashboard (`web/public`, `web/api`)

- `/api/stats` and `/api/articles` accept `?topic=`, default `defense`.
  `/api/articles` also accepts `?section=` for politics.
- New route `/politics` (rewrite in `vercel.json` and `dev_server.py`) serves the
  same dashboard page. `app.js` reads the topic from the path, and the page title
  and subtitle follow it.
- **Politics only:** a Domestic / Diplomatic / All control filters the explorer
  and the charts.
- **Sidebar:** Pages becomes Defense (`/`), Politics (`/politics`), Logs.
- **Logs:** a topic column on runs, and a topic filter.
- **Labels:** the "6 Israeli news sites" subtitle and similar text become
  data-driven (the count of sources for the topic).

### Kan text cleanup

Kan article content currently starts with "התחברו וקבלו תוכן מותאם אישית" four
times and ends with "Website created by IdeoDigital האם אתה רוצה להתנתק?".

- `parse_article` (or a Kan-specific post-step) strips both, with a test.
- A one-off script cleans existing Kan rows, like the HTML-entity cleanup did.

## Error handling

The behaviour stays the same as now, per section:

- A failed later page keeps the earlier pages.
- An empty page 1 is a warning.
- A failing section is logged, and the other sections of that source still run.
- An RSS parse failure is logged as a section error.
- An unknown topic in the API returns 400.

## Testing

Stdlib `unittest`, offline, with saved HTML or XML snapshots in `web/tests/fixtures/`:

- link extraction for each new section pattern, one fixture per new outlet section;
- RSS link reading for Ynet;
- a source with two sections returns tagged links, and a URL listed in both appears once;
- the topic → table mapping, and that unknown topics raise;
- the backfill `--days` cutoff stops at the right page;
- Kan boilerplate stripping;
- all existing tests pass after the registry change.

Before the backfill, the two sections marked "not yet probed" are checked live.

## Out of scope

- Walla and Srugim.
- Deep backfill of sections without pagination.
- Models for political articles. The propaganda pilot in `pilot/` is defense data only.
