# Article ingestion site (Vercel)

Once a day it scrapes the security/defense sections of 6 Israeli news sites, saves
**only articles not already in the database** to Supabase Postgres, and shows a
dashboard of how many articles were ingested per site per day.

No ML model runs here: the model is a separate step.

| Site | Category page | Pages walked |
|---|---|---|
| Ynet | ynet.co.il/news/category/344 | 1 (no pagination) |
| Kan News | kan.org.il/content/kan-news/defense/ | up to `MAX_PAGES` |
| Channel 13 | 13tv.co.il/news/politics/security/ | up to `MAX_PAGES` |
| Channel 14 | c14.co.il/archive/990 | 1 (no pagination) |
| I24 NEWS | i24news.tv/he/news/news/defense-news | up to `MAX_PAGES` |
| Channel 12 | mako.co.il/news-military | up to `MAX_PAGES` |

## How it works

- `lib/scraper.py`: plain HTTP scrapers (no browser). `curl_cffi` imitates Chrome,
  which gets past Channel 13's and Mako's bot checks. Title, body and publish date
  come from each article's schema.org `NewsArticle` data.
- Four sections paginate (Channel 13, Channel 12, i24, Kan), so `get_links` walks them
  page by page, up to `MAX_PAGES` (3, about 15-18 days of history). It stops early
  once a page holds nothing that is not already stored, so a normal run costs one
  or two extra page fetches and a run after an outage walks deeper by itself.
  Ynet and Channel 14 return page 1 for `?page=2`; they read one page.
- `lib/ingest.py`: for each site (all in parallel): walk the section pages, skip
  URLs already in the DB, scrape the rest, insert them, log the run.
- `api/cron.py`: `GET /api/cron`, run daily by Vercel Cron at 20:00 UTC (23:00 Israel winter time, 22:00 summer).
  It requires the `CRON_SECRET` header, so nobody else can trigger it.
  `POST /api/cron` is the dashboard's "Ingest now" button (requires sign-in).
- `api/stats.py`: `GET /api/stats?by=ingested|published&days=30`, the counts the dashboard uses (requires sign-in).
- `api/login.py`: password sign-in; sets an HttpOnly cookie that lasts a year.
- `public/index.html`: the dashboard.
- Tables (created automatically on first run): `articles` and `ingest_runs`.
  An article counts as a duplicate if it has the same `url`, or the same `source` + `title`.

## Setup

### 1. Supabase
1. Create a project at supabase.com.
2. Click **Connect** and copy the **Transaction pooler** connection string (port `6543`).
   Put your database password into it.

### 2. Vercel
1. **Add New → Project**, then import the `news_semantic_model` GitHub repo.
2. Set **Root Directory** to `web` and **Framework Preset** to `Other`.
3. Add these **Environment Variables**:
   - `DATABASE_URL`: the Supabase connection string from step 1
   - `CRON_SECRET`: any long random string
   - `DASHBOARD_PASSWORD`: the password for signing in to the dashboard. Changing it signs out every device.
   - `GITHUB_TOKEN` (optional): lets the "Ingest now" button also start the Kan job on GitHub. A fine-grained token for this repository only, with "Actions: Read and write".
4. Click **Deploy**. The cron job is picked up from `vercel.json` automatically.

To run the first ingestion right away instead of waiting for the cron:

```bash
curl -H "Authorization: Bearer YOUR_CRON_SECRET" https://YOUR-SITE.vercel.app/api/cron
```

### 3. Import your existing CSV (once, from your computer)
```bash
cd web
pip install -r requirements.txt
copy .env.example .env        # then fill in DATABASE_URL
python import_csv.py path\to\log_csv.csv --dry-run
python import_csv.py path\to\log_csv.csv
```
For a CSV without a `Source` column, add `--source "Kan News"` (or another site name).
Running the import twice is safe, because rows that already exist are skipped.

## Local tools
- `python run_local.py`: run one ingestion from your computer.
- `python backfill.py --dry-run`: show how deep a backfill would walk, write nothing.
- `python backfill.py`: one-time deep walk (25 pages, ~4-5 months) to collect
  articles from before the project started or from days when a run failed. Takes
  many minutes, which is why it is not a Vercel function. Safe to re-run.
- Kan News blocks Vercel, so it runs daily in GitHub Actions instead (`.github/workflows/kan-daily.yml`, 20:15 UTC, needs the `DATABASE_URL` repo secret).
- `python dev_server.py`: preview the dashboard at http://localhost:8000.
