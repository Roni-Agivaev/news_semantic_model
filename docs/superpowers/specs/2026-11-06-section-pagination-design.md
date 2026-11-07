# Read whole defense sections, not just page 1

Date: 2026-11-06
Status: approved, not yet implemented

## Problem

The ingester reads one page per site. Three of the six sites paginate their
defense section, so everything past the first page has never been collected.

Measured 2026-11-06, walking six pages per site and checking each URL against
the `articles` table:

| Site | Unique in 6 pages | In DB | Missing |
|---|---|---|---|
| Channel 13 | 192 | 88 | **104** |
| I24 NEWS | 144 | 56 | **88** |
| Channel 12 | 108 | 55 | **53** |
| Ynet | 40 | 40 | 0 |
| Channel 14 | 25 | 25 | 0 |

**245 articles are in these sections and not in the database.** Pagination had
not run out at page six; every page still returned a full batch of new links.

Depth maps onto age at roughly 5-6 days per page (Channel 13: page 1 is 4-9
days old, page 3 is 21-24, page 6 is 36-39). Page 1 therefore spans several days, which is why the daily cron keeps up with *new* articles and the gap is
historical: articles published before the project started, or on days when a
run failed.

Ynet and Channel 14 return identical content for `?page=2`; their single page
covers 12 and 5 days respectively and the database already holds 100% of both.
They need no change.

## Goals

- Ingest every article in each site's defense section, subject to a depth cap.
- Recover the 245 already missing.
- Keep the daily cron inside Vercel's 300 s `maxDuration`.
- Change nothing for Ynet and Channel 14.

## Non-goals

- Keyword or topic filtering. Section membership is the criterion, and all
  three paginated sites have section-scoped link patterns
  (`/item/news/politics/security/…`, `/news-military/…Article-…`,
  `/he/news/news/defense-news/artc-…`), so anything they match is in the
  section by construction. No relevance heuristic enters the dataset.
- Broadening to news sitemaps or other sections.
- Any change to scoring, the model, or the dashboard.

## Design

### 1. Per-site pagination template

Add an optional `page_url` to the three paginated entries in `SITES`
(`web/lib/scraper.py`), a format string taking `{n}`:

| Site | `page_url` |
|---|---|
| Channel 13 | `https://13tv.co.il/news/politics/security/page/{n}/` |
| Channel 12 | `https://www.mako.co.il/news-military?page={n}` |
| I24 NEWS | `https://www.i24news.tv/he/news/news/defense-news?page={n}` |

Sites without `page_url` (Ynet, Channel 14, Kan News) read one page exactly as
they do today.

### 2. `get_links` walks pages, with an adaptive stop rule

```
get_links(source, schedule=RETRY_AT_S, known=None, max_pages=MAX_PAGES)
```

- Page 1 is `category_url`; pages 2+ are `page_url.format(n=N)`.
- Each page is fetched through the existing `_attempts(schedule)` cold-cache
  retry, so an i24 shell cannot silently truncate the walk.
- After each page: collect its links, drop ones already seen in this walk.
- **Stop before fetching page N+1 when** every link on page N is already
  accounted for, meaning each one was either seen earlier in this same walk
  or reported stored by `known`. Also stop when a page yields no links at
  all, or when `max_pages` is reached.
- `known` is an optional callable `(urls) -> set_of_stored_urls`. It keeps
  `scraper.py` free of any database import: `ingest.py` passes
  `lambda urls: db.existing_urls(conn, urls)`. When `known` is `None` nothing
  counts as stored, so the walk stops only on a page that repeats links
  already seen in the walk, on an empty page, or at `max_pages`.
- Returns the union across pages, order preserved, deduplicated.

`MAX_PAGES = 3` for the cron: about 15-18 days of history, enough to absorb a
two-week outage. This is a choice about how long an unattended outage should
heal itself, not a measured value.

Why adaptive rather than a fixed depth: in steady state the walk stops at page
1 or 2, costing one or two extra *category* fetches, because article bodies are
already skipped by `existing_urls`. After an outage it walks deeper on its own
until it has caught up. A fixed depth does not self-heal.

### 3. One-time backfill, run locally

The first deep walk cannot run on Vercel. I24's share alone is ~88 articles at
15-20 s each on a cold cache, about 7 minutes with 4 workers, against a 300 s
ceiling.

A one-off script (`web/backfill.py`, not deployed as a function) walks with
`max_pages≈25`, roughly 4-5 months back at 5-6 days per page, writing
through the same
`db.insert_articles` to the same Supabase. It is run once from a developer
machine. After it, the cron only ever meets a page or two of new material.

The backfill depends on the i24 cold-cache retry fix already in the working
tree; without it i24 is unreadable, so that lands first.

### 4. Data model

No schema change. Backfilled rows are ordinary `origin='scraper'` articles.
Existing dedup (`url` unique, `(source, title)` unique, title-only refill)
applies unchanged.

## Testing

Following the existing `web/tests/` pattern: stdlib `unittest`, no network, no
new dependency.

- A fake paginated site of known size, with `fetch` patched: the walk collects
  every page's links and stops at the last one.
- Stop rule: when `known` reports page 2's links are all already stored, page 3
  is never fetched.
- Cap: a site that never runs out stops at `max_pages`.
- No regression: a site without `page_url` fetches exactly one page.
- The three cold-cache retry tests stay green.

## Risks

- **Depth is a guess.** `MAX_PAGES = 3` is chosen, not measured. If outages run
  longer than ~15 days the gap returns; the backfill script is the remedy.
- **Page URL patterns can change.** A site altering its pagination scheme turns
  pages 2+ into zero-link fetches. The walk degrades to today's behaviour
  (page 1 only) rather than failing, which makes the breakage quiet. Worth a
  follow-up: surface per-site `links_found` trends on the dashboard.
- **Backfill volume.** 245+ articles arriving at once will show as one large
  spike in the dashboard's per-day chart, grouped by publish date, not a
  mistake.
- **Pagination was verified to six pages only**, on all three sites. Deeper
  pages are assumed to behave the same; the backfill will confirm.

## Rollout order

1. Commit the i24 cold-cache retry fix and its tests (already written).
2. Implement pagination + tests; deploy.
3. Run the backfill locally once; confirm the 245 land.
4. Watch the next cron run: `links_found` should rise for the three sites, and
   `new_articles` should fall back to normal within a day or two.
