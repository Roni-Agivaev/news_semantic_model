"""
The scraper reports what it does through an optional `log` callable, so the
/logs page can show which pages were read, why a walk stopped and why an
article failed. No network: fake sites from test_scraper_pagination.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from lib import scraper  # noqa: E402
from curl_cffi.requests.exceptions import HTTPError  # noqa: E402
from test_scraper_pagination import (  # noqa: E402
    PAGE_1, SOURCE, FakeSite, article_urls, page_n, section_page)
from test_scraper_retry import ARTICLE_FULL, ARTICLE_SHELL  # noqa: E402


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, level, step, message, url=None, **detail):
        self.events.append({"level": level, "step": step, "message": message, "url": url, "detail": detail})

    def levels(self):
        return [e["level"] for e in self.events]

    def text(self):
        return "\n".join(e["message"] for e in self.events)


class Forbidden:
    status_code = 403


class Base(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(scraper.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        self.log = Recorder()


class WalkEventsTest(Base):
    def walk(self, site, **kw):
        with mock.patch.object(scraper, "fetch", site.fetch):
            return scraper.get_links(SOURCE, log=self.log, **kw)

    def test_each_page_read_is_logged_with_its_link_counts(self):
        site = FakeSite({PAGE_1: section_page("a1", "a2"), page_n(2): section_page("b1")})
        self.walk(site, max_pages=2)
        pages = [e for e in self.log.events if e["detail"].get("page")]
        self.assertEqual([e["detail"]["page"] for e in pages], [1, 2])
        self.assertEqual([e["detail"]["links"] for e in pages], [2, 1])
        self.assertEqual(pages[0]["url"], PAGE_1)
        self.assertIn("attempts", pages[0]["detail"])

    def test_stopping_because_nothing_is_new_is_explained(self):
        site = FakeSite({PAGE_1: section_page("a1", "a2"), page_n(2): section_page("b1")})
        stored = set(article_urls("a1", "a2"))
        self.walk(site, max_pages=3, known=lambda urls: {u for u in urls if u in stored})
        self.assertIn("nothing new", self.log.text())
        self.assertNotIn("error", self.log.levels())

    def test_reaching_the_page_limit_is_explained(self):
        site = FakeSite({PAGE_1: section_page("a1"), page_n(2): section_page("b1")})
        self.walk(site, max_pages=2)
        self.assertIn("page limit", self.log.text())

    def test_a_failed_later_page_is_a_warning(self):
        site = FakeSite({PAGE_1: section_page("a1"), page_n(2): HTTPError("boom", response=Forbidden())})
        links = self.walk(site, max_pages=3)
        self.assertEqual(links, article_urls("a1"))
        warns = [e for e in self.log.events if e["level"] == "warn"]
        self.assertEqual(len(warns), 1)
        self.assertIn("403", warns[0]["message"])
        self.assertEqual(warns[0]["url"], page_n(2))

    def test_walk_without_a_logger_still_works(self):
        site = FakeSite({PAGE_1: section_page("a1")})
        with mock.patch.object(scraper, "fetch", site.fetch):
            self.assertEqual(scraper.get_links(SOURCE, max_pages=1), article_urls("a1"))


class ArticleEventsTest(Base):
    URL = "https://www.i24news.tv/he/news/news/defense-news/artc-aaa111"

    def scrape(self, fetch, **kw):
        with mock.patch.object(scraper, "fetch", fetch):
            return scraper.scrape_article("I24 NEWS", self.URL, log=self.log, **kw)

    def test_a_scraped_article_is_logged_with_its_title(self):
        self.assertIsNotNone(self.scrape(lambda u, timeout=20: ARTICLE_FULL))
        (e,) = self.log.events
        self.assertEqual(e["level"], "info")
        self.assertIn("Headline", e["message"])
        self.assertEqual(e["url"], self.URL)

    def test_a_blocked_article_is_an_error_with_the_status_code(self):
        def fetch(url, timeout=20):
            raise HTTPError("HTTP Error 403", response=Forbidden())
        self.assertIsNone(self.scrape(fetch))
        (e,) = self.log.events
        self.assertEqual(e["level"], "error")
        self.assertIn("HTTP 403", e["message"])

    def test_falling_back_to_the_sitemap_title_is_a_warning(self):
        def fetch(url, timeout=20):
            raise HTTPError("HTTP Error 403", response=Forbidden())
        article = self.scrape(fetch, fallback={"title": "T", "published_at": None})
        self.assertEqual(article["content"], "")
        (e,) = self.log.events
        self.assertEqual(e["level"], "warn")
        self.assertIn("title only", e["message"])
        self.assertIn("HTTP 403", e["message"])

    def test_an_empty_shell_reports_too_little_text_and_the_attempts(self):
        self.assertIsNone(self.scrape(lambda u, timeout=20: ARTICLE_SHELL))
        (e,) = self.log.events
        self.assertEqual(e["level"], "error")
        self.assertRegex(e["message"], r"no title|too short")
        self.assertEqual(e["detail"]["attempts"], len(scraper.RETRY_AT_S))

    def test_a_timeout_is_named(self):
        def fetch(url, timeout=20):
            raise TimeoutError("timed out")
        self.scrape(fetch, schedule=(0,))
        self.assertIn("TimeoutError", self.log.events[0]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
