"""
db.ensure_schema used to run the whole SCHEMA script - including ALTER TABLE ...
ENABLE ROW LEVEL SECURITY, which takes an exclusive lock - on every cold start.
Two connections doing that at once deadlock (seen 2026-11-08 when the dashboard
loaded /api/stats and /api/articles together). The DDL must only run when the
schema is actually missing.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db  # noqa: E402


class FakeConn:
    def __init__(self, ready):
        self.ready = ready
        self.statements = []
        self.commits = 0

    def execute(self, sql, params=None):
        self.statements.append(sql)
        ready = self.ready

        class Result:
            def fetchone(self_inner):
                return {"ready": ready}

        return Result()

    def commit(self):
        self.commits += 1


class EnsureSchemaTest(unittest.TestCase):
    def setUp(self):
        db._schema_ready = False
        self.addCleanup(setattr, db, "_schema_ready", False)

    def test_existing_schema_runs_no_ddl(self):
        conn = FakeConn(ready=True)
        db.ensure_schema(conn)
        self.assertFalse(any(db.SCHEMA in s for s in conn.statements),
                         "SCHEMA (with its exclusive-lock ALTER TABLE) ran on an existing database")
        self.assertGreaterEqual(conn.commits, 1, "the check's transaction must be closed")

    def test_missing_schema_is_created(self):
        conn = FakeConn(ready=False)
        db.ensure_schema(conn)
        self.assertTrue(any(db.SCHEMA in s for s in conn.statements))

    def test_checks_only_once_per_process(self):
        conn = FakeConn(ready=True)
        db.ensure_schema(conn)
        db.ensure_schema(conn)
        self.assertEqual(len(conn.statements), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
