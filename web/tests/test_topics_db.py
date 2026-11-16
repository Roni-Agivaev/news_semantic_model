"""
Politics articles live in their own table. Every article query picks its table
through db.table_for(topic), so a topic string never reaches SQL as-is, and
run summaries carry the topic. No database: a fake connection records SQL.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db  # noqa: E402
from lib.events import RunLog  # noqa: E402


class Recorded:
    def __init__(self, rows=None, one=None):
        self.rows, self.one, self.rowcount = rows or [], one, 0

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


class FakeConn:
    def __init__(self, one=None):
        self.calls = []
        self.one = one

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return Recorded(one=self.one)

    def cursor(self):
        conn = self

        class Cur:
            rowcount = 0

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                conn.calls.append((sql, params))
                self.rowcount = 0 if sql.lstrip().startswith("UPDATE") else 1

        return Cur()

    def commit(self):
        pass

    def sql(self):
        return "\n".join(s for s, _ in self.calls)


class TableForTest(unittest.TestCase):
    def test_topics_map_to_tables(self):
        self.assertEqual(db.table_for("defense"), "articles")
        self.assertEqual(db.table_for("politics"), "political_articles")

    def test_unknown_topic_raises(self):
        for bad in ("sports", "articles; DROP TABLE articles", "", None):
            with self.assertRaises(ValueError):
                db.table_for(bad)


class SchemaTest(unittest.TestCase):
    def test_schema_creates_the_politics_table_and_topic_columns(self):
        for ddl in ("CREATE TABLE IF NOT EXISTS political_articles",
                    "ALTER TABLE articles ADD COLUMN IF NOT EXISTS section",
                    "ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS topic",
                    "ALTER TABLE scrape_runs ADD COLUMN IF NOT EXISTS topic",
                    "ALTER TABLE political_articles ENABLE ROW LEVEL SECURITY"):
            self.assertIn(ddl, db.SCHEMA)

    def test_schema_check_requires_the_new_pieces(self):
        self.assertIn("public.political_articles", db.SCHEMA_CHECK)
        self.assertIn("= 5", db.SCHEMA_CHECK)
        self.assertIn("'topic'", db.SCHEMA_CHECK)
        self.assertIn("'section'", db.SCHEMA_CHECK)


class QueriesTest(unittest.TestCase):
    ARTICLE = {"source": "Maariv", "url": "https://www.maariv.co.il/news/politics/article-1",
               "title": "t", "content": "body", "published_at": None, "section": "combined"}

    def test_insert_writes_the_topic_table_with_the_section(self):
        conn = FakeConn()
        db.insert_articles(conn, [self.ARTICLE], topic="politics")
        self.assertIn("political_articles", conn.sql())
        self.assertNotRegex(conn.sql(), r"\b(INTO|UPDATE) articles\b")
        insert = next(p for s, p in conn.calls if "INSERT INTO political_articles" in s)
        self.assertIn("combined", insert)

    def test_defense_insert_defaults_the_section(self):
        conn = FakeConn()
        a = {k: v for k, v in self.ARTICLE.items() if k != "section"}
        db.insert_articles(conn, [a])
        insert = next(p for s, p in conn.calls if "INSERT INTO articles" in s)
        self.assertIn("defense", insert)

    def test_existing_urls_reads_the_topic_table(self):
        conn = FakeConn()
        db.existing_urls(conn, ["u"], topic="politics")
        self.assertIn("FROM political_articles", conn.sql())

    def test_log_run_records_the_topic(self):
        conn = FakeConn()
        db.log_run(conn, "Maariv", 3, 1, 0, run_id="r1", topic="politics")
        sql, params = conn.calls[0]
        self.assertIn("topic", sql)
        self.assertIn("politics", params)

    def test_start_scrape_run_records_the_topic(self):
        conn = FakeConn()
        db.start_scrape_run(conn, "r1", "cron", ["Maariv"], topic="politics")
        sql, params = conn.calls[0]
        self.assertIn("topic", sql)
        self.assertIn("politics", params)

    def test_stats_for_politics_never_reads_the_defense_table(self):
        conn = FakeConn(one={"stats": {"health": []}})
        db.stats(conn, topic="politics", section="domestic")
        sql, params = conn.calls[-1]
        self.assertIn("FROM political_articles", sql)
        self.assertNotRegex(sql, r"FROM articles\b")
        self.assertEqual(params["topic"], "politics")
        self.assertEqual(params["section"], "domestic")

    def test_stats_can_limit_run_history_to_current_sources(self):
        """Removed outlets (Davar, Zman Israel) keep their old run rows; the
        dashboard should not list them as failing sites."""
        conn = FakeConn(one={"stats": {"health": []}})
        db.stats(conn, topic="defense", sources=["Ynet", "Maariv"])
        sql, params = conn.calls[-1]
        self.assertIn("source = ANY(%(sources)s)", sql)
        self.assertEqual(params["sources"], ["Ynet", "Maariv"])

    def test_search_filters_by_section(self):
        conn = FakeConn()
        db.search_articles(conn, topic="politics", section="diplomatic")
        sql, params = conn.calls[-1]
        self.assertIn("FROM political_articles", sql)
        self.assertEqual(params["section"], "diplomatic")

    def test_unknown_topic_is_refused_before_any_sql(self):
        conn = FakeConn()
        with self.assertRaises(ValueError):
            db.stats(conn, topic="sports")
        self.assertEqual(conn.calls, [])


class RunLogTopicTest(unittest.TestCase):
    def test_the_topic_reaches_the_writer(self):
        seen = {}

        class Writer:
            def start_run(self, run_id, trigger, sources, topic):
                seen["topic"] = topic

            def add_events(self, events): pass
            def finish_run(self, *a): pass
            def close(self): pass

        log = RunLog("cron", ["Maariv"], Writer(), topic="politics")
        log.start()
        self.assertEqual(seen["topic"], "politics")
        self.assertEqual(log.topic, "politics")


if __name__ == "__main__":
    unittest.main(verbosity=2)
