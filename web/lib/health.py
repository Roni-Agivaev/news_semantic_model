"""
One site's scraping health, from its recent ingest runs.

    ok        working
    degraded  the last run worked, but too many recent runs failed
    failing   the last run failed
    stale     no successful run for STALE_HOURS (the cron may not be running)
    none      no runs recorded

"degraded" exists because i24 failed half its runs for weeks while the old
dashboard, which only looked at the last success, called it OK.
"""
from datetime import datetime

STALE_HOURS = 26
DEGRADED_BELOW = 0.8   # share of recent runs that must succeed
MIN_RUNS_FOR_TREND = 4  # fewer runs than this is too little to call a trend


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")) if isinstance(ts, str) else ts


def site_status(last_ok, history, now):
    """`history` is the recent runs, oldest first, each with an "ok" flag;
    `last_ok` is the time of the most recent successful run, or None."""
    if not history:
        return "none"
    if not history[-1]["ok"]:
        return "failing"
    if last_ok is None or (now - _parse(last_ok)).total_seconds() > STALE_HOURS * 3600:
        return "stale"
    if len(history) >= MIN_RUNS_FOR_TREND:
        share = sum(1 for r in history if r["ok"]) / len(history)
        if share < DEGRADED_BELOW:
            return "degraded"
    return "ok"
