"""
A site's health from its recent runs. The old dashboard only asked "did the last
run succeed, and was there a success in the last 26 h", so i24 read "OK" while
failing half its runs (Nov 2026). These tests pin the stricter rule.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.health import site_status  # noqa: E402

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def runs(*oks):
    """Run history, oldest first, one run per day ending yesterday evening."""
    n = len(oks)
    return [{"ok": ok, "ran_at": (NOW - timedelta(days=n - i, hours=-8)).isoformat()} for i, ok in enumerate(oks)]


def last_ok_of(history):
    oks = [r["ran_at"] for r in history if r["ok"]]
    return oks[-1] if oks else None


class SiteStatusTest(unittest.TestCase):
    def status(self, history, last_ok="auto"):
        if last_ok == "auto":
            last_ok = last_ok_of(history)
        return site_status(last_ok, history, NOW)

    def test_no_runs(self):
        self.assertEqual(self.status([]), "none")

    def test_all_good(self):
        self.assertEqual(self.status(runs(*[True] * 14)), "ok")

    def test_last_run_failed_is_failing(self):
        self.assertEqual(self.status(runs(*[True] * 13, False)), "failing")

    def test_half_the_runs_failing_is_degraded_even_if_the_last_one_worked(self):
        """The i24 case: alternating failures, last run happened to succeed."""
        self.assertEqual(self.status(runs(*[False, True] * 7)), "degraded")

    def test_one_old_failure_is_still_ok(self):
        self.assertEqual(self.status(runs(False, *[True] * 13)), "ok")

    def test_no_success_for_more_than_26h_is_stale(self):
        history = [{"ok": True, "ran_at": (NOW - timedelta(hours=30)).isoformat()}]
        self.assertEqual(self.status(history), "stale")

    def test_too_few_runs_to_call_degraded(self):
        """Two runs, one bad: not enough evidence for a trend."""
        self.assertEqual(self.status(runs(False, True)), "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
