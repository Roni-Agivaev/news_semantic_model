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
from curl_cffi import requests as curl_requests  # noqa: E402

HTTP_ERROR = curl_requests.exceptions.HTTPError

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

if __name__ == "__main__":
    unittest.main(verbosity=2)
