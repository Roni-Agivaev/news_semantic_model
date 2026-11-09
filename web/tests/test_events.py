"""
RunLog collects step-by-step events of one scrape run for the /logs page.
It writes them in small batches so the page can follow a run live, and it must
never break the scrape it is describing: a failing writer is swallowed.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.events import RunLog  # noqa: E402


class FakeWriter:
    def __init__(self, fail=False):
        self.fail = fail
        self.started, self.batches, self.finished = [], [], []

    def start_run(self, run_id, trigger, sources):
        self._maybe_fail()
        self.started.append((run_id, trigger, sources))

    def add_events(self, events):
        self._maybe_fail()
        self.batches.append(list(events))

    def finish_run(self, run_id, status, new_articles, summary):
        self._maybe_fail()
        self.finished.append((run_id, status, new_articles, summary))

    def close(self):
        pass

    def _maybe_fail(self):
        if self.fail:
            raise RuntimeError("database is down")

    @property
    def events(self):
        return [e for b in self.batches for e in b]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RunLogTest(unittest.TestCase):
    def make(self, writer=None, **kw):
        self.writer = writer or FakeWriter()
        self.clock = Clock()
        return RunLog("manual", ["Ynet"], writer=self.writer, clock=self.clock, **kw)

    def test_start_records_trigger_and_sources(self):
        log = self.make()
        log.start()
        self.assertEqual(self.writer.started, [(log.run_id, "manual", ["Ynet"])])

    def test_site_logger_tags_events_with_source_level_and_detail(self):
        log = self.make()
        site = log.for_site("Ynet")
        site("warn", "article", "Failed: HTTP 403", url="https://x/1", attempts=1)
        log.finish(new_articles=0)
        (e,) = self.writer.events
        self.assertEqual((e["source"], e["level"], e["step"], e["message"], e["url"]),
                         ("Ynet", "warn", "article", "Failed: HTTP 403", "https://x/1"))
        self.assertEqual(e["detail"], {"attempts": 1})
        self.assertEqual(e["run_id"], log.run_id)
        self.assertIn("at", e)

    def test_events_are_written_while_the_run_is_still_going(self):
        log = self.make(flush_every_s=2.0)
        site = log.for_site("Ynet")
        site("info", "section", "Page 1")
        self.assertEqual(self.writer.batches, [], "first event should wait for a batch")
        self.clock.now = 2.5
        site("info", "section", "Page 2")
        self.assertEqual([e["message"] for e in self.writer.events], ["Page 1", "Page 2"])

    def test_a_full_buffer_is_written_without_waiting(self):
        log = self.make(flush_every_s=60, max_buffer=3)
        site = log.for_site("Ynet")
        for i in range(3):
            site("info", "article", f"a{i}")
        self.assertEqual(len(self.writer.events), 3)

    def test_finish_writes_the_rest_and_the_run_status(self):
        log = self.make(flush_every_s=60)
        site = log.for_site("Ynet")
        site("info", "article", "ok")
        site("warn", "article", "title only")
        log.finish(new_articles=4, summary={"Ynet": {"new_articles": 4}})
        self.assertEqual(len(self.writer.events), 2)
        self.assertEqual(self.writer.finished,
                         [(log.run_id, "warn", 4, {"Ynet": {"new_articles": 4}})])

    def test_status_is_error_when_any_event_is_an_error(self):
        log = self.make()
        log.for_site("Ynet")("warn", "x", "w")
        log.for_site("Ynet")("error", "x", "e")
        log.finish(new_articles=0)
        self.assertEqual(self.writer.finished[0][1], "error")

    def test_status_is_ok_with_only_info_events(self):
        log = self.make()
        log.for_site("Ynet")("info", "x", "fine")
        log.finish(new_articles=1)
        self.assertEqual(self.writer.finished[0][1], "ok")

    def test_a_failing_writer_never_breaks_the_run(self):
        log = self.make(writer=FakeWriter(fail=True), max_buffer=1)
        log.start()
        log.for_site("Ynet")("info", "x", "still running")
        log.finish(new_articles=0)  # no exception is the assertion

    def test_writer_is_given_up_after_repeated_failures(self):
        """A dead database must not slow every scrape step with a 15 s connect timeout."""
        calls = []
        writer = FakeWriter(fail=True)
        original = writer.add_events
        writer.add_events = lambda ev: (calls.append(1), original(ev))
        log = self.make(writer=writer, max_buffer=1)
        for _ in range(10):
            log.for_site("Ynet")("info", "x", "m")
        self.assertLessEqual(len(calls), 3)

    def test_events_from_many_threads_are_all_kept(self):
        log = self.make(flush_every_s=60, max_buffer=7)
        site = log.for_site("Ynet")
        threads = [threading.Thread(target=lambda: [site("info", "a", "m") for _ in range(50)])
                   for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log.finish(new_articles=0)
        self.assertEqual(len(self.writer.events), 200)

    def test_long_messages_are_cut(self):
        log = self.make()
        log.for_site("Ynet")("error", "x", "e" * 5000)
        log.finish(new_articles=0)
        self.assertLessEqual(len(self.writer.events[0]["message"]), 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
