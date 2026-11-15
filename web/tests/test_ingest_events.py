"""
ingest_site narrates a site's run for the /logs page: what the sitemap and
section gave, how many links were new, what was saved, and a closing summary.
The database and the network are faked.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import ingest  # noqa: E402


class FakeDb:
    def __init__(self, stored=()):
        self.stored = set(stored)
        self.runs = []

    def connect(self):
        return mock.Mock()

    def existing_urls(self, conn, urls, topic="defense"):
        self.topics = getattr(self, "topics", set()) | {topic}
        return {u for u in urls if u in self.stored}

    def insert_articles(self, conn, articles, topic="defense"):
        self.inserted = list(articles)
        self.topics = getattr(self, "topics", set()) | {topic}
        return len(articles)

    def log_run(self, conn, **kw):
        self.runs.append(kw)


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, level, step, message, url=None, **detail):
        self.events.append((level, step, message))

    def text(self):
        return "\n".join(m for _, _, m in self.events)


def article(url, published_at=None):
    return {"source": "Ynet", "url": url, "title": url, "content": "x" * 100, "published_at": published_at}


class IngestEventsTest(unittest.TestCase):
    def run_site(self, links=None, links_error=None, scraped=None, stored=(), topic="defense", since=None):
        fake = FakeDb(stored)
        log = Recorder()

        def get_links(topic_, source, known=None, max_pages=None, log=None):
            if links_error:
                raise links_error
            return [(u, "domestic" if topic_ == "politics" else "defense") for u in links]

        def scrape_article(source, url, fallback=None, log=None):
            return scraped(url) if scraped else article(url)

        with mock.patch.object(ingest, "db", fake), \
             mock.patch.object(ingest, "get_links", get_links), \
             mock.patch.object(ingest, "scrape_article", scrape_article):
            result = ingest.ingest_site(topic, "Ynet", log=log, run_id="r1", since=since)
        return result, log, fake

    def test_counts_and_summary_are_narrated(self):
        result, log, fake = self.run_site(links=["u1", "u2", "u3"], stored={"u1"})
        text = log.text()
        self.assertIn("3 links", text)
        self.assertIn("1 already stored", text)
        self.assertIn("2 to scrape", text)
        self.assertIn("Saved 2 new", text)
        self.assertEqual(log.events[-1][0], "info")
        self.assertEqual(log.events[-1][1], "done")
        self.assertEqual(fake.runs[0]["run_id"], "r1")

    def test_failed_articles_make_the_summary_a_warning(self):
        result, log, _ = self.run_site(links=["u1", "u2"], scraped=lambda u: None if u == "u2" else article(u))
        self.assertEqual(result["failed"], 1)
        self.assertEqual(log.events[-1][0], "warn")
        self.assertIn("1 failed", log.events[-1][2])

    def test_a_dead_section_page_is_an_error(self):
        result, log, _ = self.run_site(links_error=RuntimeError("connection refused"))
        self.assertTrue(result["error"])
        errors = [m for lvl, _, m in log.events if lvl == "error"]
        self.assertTrue(any("connection refused" in m for m in errors), log.events)

    def test_nothing_to_scrape_says_so(self):
        _, log, _ = self.run_site(links=["u1"], stored={"u1"})
        self.assertIn("0 to scrape", log.text())


class DroppedConnectionTest(IngestEventsTest):
    def test_a_connection_dropped_mid_run_is_reopened_and_the_save_retried(self):
        """2026-11-15: the database closed every connection during a long
        politics backfill, and five sources lost their scraped articles."""
        import psycopg

        class Flaky(FakeDb):
            def __init__(self):
                super().__init__()
                self.connects = 0
                self.fail_next_insert = True

            def connect(self):
                self.connects += 1
                return mock.Mock()

            def insert_articles(self, conn, articles, topic="defense"):
                if self.fail_next_insert:
                    self.fail_next_insert = False
                    raise psycopg.OperationalError("server closed the connection unexpectedly")
                return super().insert_articles(conn, articles, topic=topic)

        fake = Flaky()
        log = Recorder()
        with mock.patch.object(ingest, "db", fake), \
             mock.patch.object(ingest, "get_links", lambda t, s, **kw: [("u1", "defense")]), \
             mock.patch.object(ingest, "scrape_article", lambda s, u, **kw: article(u)):
            result = ingest.ingest_site("defense", "Ynet", log=log, run_id="r1")
        self.assertIsNone(result["error"])
        self.assertEqual(result["new_articles"], 1)
        self.assertEqual(fake.connects, 2)
        self.assertEqual(len(fake.runs), 1)


class TopicTest(IngestEventsTest):
    def test_articles_carry_their_section_and_go_to_the_topic(self):
        _, _, fake = self.run_site(links=["u1"], topic="politics")
        self.assertEqual(fake.inserted[0]["section"], "domestic")
        self.assertEqual(fake.topics, {"politics"})
        self.assertEqual(fake.runs[0]["topic"], "politics")

    def test_since_drops_older_articles(self):
        from datetime import datetime, timezone
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new = datetime(2026, 11, 1, tzinfo=timezone.utc)
        _, log, fake = self.run_site(links=["u1", "u2"],
                                     scraped=lambda u: article(u, old if u == "u1" else new),
                                     since=datetime(2026, 8, 17, tzinfo=timezone.utc))
        self.assertEqual([a["url"] for a in fake.inserted], ["u2"])
        self.assertIn("Skipped 1 published before 2026-08-17", log.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
