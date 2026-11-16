"""
backfill.py walks one topic's sections deep and keeps only articles published
inside --days (default 90). The CLI parsing is a pure function so it can be
tested without a database.
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backfill  # noqa: E402

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


class BuildArgsTest(unittest.TestCase):
    def test_defaults_are_every_defense_source_and_90_days(self):
        topic, sources, max_pages, since, dry = backfill.build_args([], now=NOW)
        self.assertEqual(topic, "defense")
        self.assertIn("Maariv", sources)
        self.assertEqual(max_pages, backfill.BACKFILL_PAGES)
        self.assertEqual(since, NOW - timedelta(days=90))
        self.assertFalse(dry)

    def test_politics_with_named_sources(self):
        topic, sources, _, _, _ = backfill.build_args(["--topic", "politics", "Maariv", "JDN"], now=NOW)
        self.assertEqual((topic, sources), ("politics", ["Maariv", "JDN"]))

    def test_days_zero_means_no_cutoff(self):
        self.assertIsNone(backfill.build_args(["--days", "0"], now=NOW)[3])

    def test_unknown_topic_or_source_is_an_error(self):
        with self.assertRaises(SystemExit):
            backfill.build_args(["--topic", "sports"], now=NOW)
        with self.assertRaises(SystemExit):
            backfill.build_args(["--topic", "politics", "Nope"], now=NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
