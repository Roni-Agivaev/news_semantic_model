"""
i24 serves a ~7KB JavaScript shell on a cold edge-cache miss and only serves the
rendered page 10-15 s later (measured 2026-11-06: category page still a shell at
0/3/6 s, full at 10 s; articles first parseable at 1 s, 11 s and 15.6 s).

These tests drive the scraper against a page that renders 12 s after the first
request, using a virtual clock, so they are deterministic and hit no network.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import scraper  # noqa: E402

RENDER_AFTER_S = 12.0  # within the measured 10-15 s window
TIME_BUDGET_S = 45.0   # one page must not eat the cron's 300 s budget

CATEGORY_SHELL = "<html><head><title>i24</title></head><body><div id=root></div></body></html>"
CATEGORY_FULL = (
    "<html><body>"
    '<a href="/he/news/news/defense-news/artc-aaa111">one</a>'
    '<a href="/he/news/news/defense-news/artc-bbb222">two</a>'
    "</body></html>"
)
ARTICLE_SHELL = "<html><head><title>i24</title></head><body><div id=root></div></body></html>"
ARTICLE_FULL = (
    "<html><head>"
    '<script type="application/ld+json">'
    '{"@type":"NewsArticle","headline":"Headline",'
    '"articleBody":"' + "Body text that is comfortably longer than the fifty character minimum. " * 2 + '",'
    '"datePublished":"2026-11-05T18:00:00+02:00"}'
    "</script></head>"
    "<body><h1>Headline</h1><p>"
    + "Body text that is comfortably longer than the fifty character minimum. " * 2
    + "</p></body></html>"
)


class VirtualClock:
    """time.sleep() advances a fake clock instead of really sleeping."""

    def __init__(self):
        self.now = 0.0
        self.fetches = []

    def sleep(self, seconds):
        self.now += seconds

    def page(self, shell, full):
        def fetch(url, timeout=20):
            self.fetches.append((round(self.now, 1), url))
            return full if self.now >= RENDER_AFTER_S else shell

        return fetch


class ColdCacheRetryTest(unittest.TestCase):
    def setUp(self):
        self.clock = VirtualClock()
        patch_sleep = mock.patch.object(scraper.time, "sleep", self.clock.sleep)
        patch_sleep.start()
        self.addCleanup(patch_sleep.stop)

    def _report(self):
        return (f"gave up at t={self.clock.now:.0f}s after "
                f"{len(self.clock.fetches)} fetches at "
                f"{[t for t, _ in self.clock.fetches]}s; page renders at {RENDER_AFTER_S:.0f}s")

    def test_get_links_recovers_category_page_that_renders_after_12s(self):
        fetch = self.clock.page(CATEGORY_SHELL, CATEGORY_FULL)
        with mock.patch.object(scraper, "fetch", fetch):
            links = scraper.get_links("I24 NEWS")
        self.assertEqual(
            links,
            ["https://www.i24news.tv/he/news/news/defense-news/artc-aaa111",
             "https://www.i24news.tv/he/news/news/defense-news/artc-bbb222"],
            msg=f"category page never read: {self._report()}",
        )

    def test_scrape_article_recovers_article_that_renders_after_12s(self):
        url = "https://www.i24news.tv/he/news/news/defense-news/artc-aaa111"
        fetch = self.clock.page(ARTICLE_SHELL, ARTICLE_FULL)
        with mock.patch.object(scraper, "fetch", fetch):
            article = scraper.scrape_article("I24 NEWS", url)
        self.assertIsNotNone(article, msg=f"article never read: {self._report()}")
        self.assertEqual(article["title"], "Headline")
        self.assertTrue(article["content"])

    def test_retry_window_stays_within_time_budget(self):
        """A page that never renders must give up well inside the cron's budget."""
        never = lambda url, timeout=20: ARTICLE_SHELL  # noqa: E731
        with mock.patch.object(scraper, "fetch", never):
            article = scraper.scrape_article(
                "I24 NEWS", "https://www.i24news.tv/he/news/news/defense-news/artc-zzz999")
        self.assertIsNone(article)
        self.assertLessEqual(
            self.clock.now, TIME_BUDGET_S,
            msg=f"retrying one article burned {self.clock.now:.0f}s (budget {TIME_BUDGET_S:.0f}s)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
