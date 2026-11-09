"""
Step-by-step events of one scrape run, shown on the /logs page.

RunLog buffers events and writes them in small batches (every `flush_every_s`
seconds or `max_buffer` events), so the page can follow a run while it is
going. Logging must never break the scrape it describes: every writer error is
printed (it lands in Vercel's function log) and otherwise ignored.

A site logger is a plain callable, `log(level, step, message, url=None, **detail)`,
which is what lib/scraper.py accepts - the scraper knows nothing about storage.
"""
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

LEVELS = ("info", "warn", "error")
MAX_MESSAGE = 500
MAX_WRITER_FAILURES = 3  # consecutive; after that the run stops trying to log


def null_log(level, step, message, url=None, **detail):
    """The logger used when nobody is listening."""


class RunLog:
    def __init__(self, trigger, sources, writer, clock=time.monotonic,
                 flush_every_s=2.0, max_buffer=40):
        self.run_id = uuid.uuid4().hex[:12]
        self.trigger = trigger
        self.sources = list(sources)
        self.writer = writer
        self.clock = clock
        self.flush_every_s = flush_every_s
        self.max_buffer = max_buffer
        self._buffer = []
        self._lock = threading.Lock()        # guards the buffer
        self._write_lock = threading.Lock()  # one writer call at a time
        self._last_flush = clock()
        self._worst = "info"
        self._failures = 0

    # ---- recording -------------------------------------------------------
    def start(self):
        self._safe(self.writer.start_run, self.run_id, self.trigger, self.sources)

    def for_site(self, source):
        def log(level, step, message, url=None, **detail):
            self.event(source, level, step, message, url=url, **detail)
        return log

    def event(self, source, level, step, message, url=None, **detail):
        level = level if level in LEVELS else "info"
        event = {
            "run_id": self.run_id,
            "at": datetime.now(timezone.utc),
            "source": source,
            "level": level,
            "step": step,
            "message": str(message)[:MAX_MESSAGE],
            "url": url,
            "detail": detail or None,
        }
        with self._lock:
            self._buffer.append(event)
            if LEVELS.index(level) > LEVELS.index(self._worst):
                self._worst = level
            due = (len(self._buffer) >= self.max_buffer
                   or self.clock() - self._last_flush >= self.flush_every_s)
        if due:
            self.flush()

    def flush(self):
        with self._lock:
            batch, self._buffer = self._buffer, []
            self._last_flush = self.clock()
        if batch:
            self._safe(self.writer.add_events, batch)

    def finish(self, new_articles, summary=None):
        self.flush()
        status = {"info": "ok", "warn": "warn", "error": "error"}[self._worst]
        self._safe(self.writer.finish_run, self.run_id, status, new_articles, summary)
        self._safe(self.writer.close)

    # ---- helpers ---------------------------------------------------------
    def _safe(self, fn, *args):
        with self._write_lock:
            if self._failures >= MAX_WRITER_FAILURES:
                return  # given up: a dead database must not slow the scrape
            try:
                fn(*args)
                self._failures = 0
            except Exception as e:  # logging must never stop a scrape
                self._failures += 1
                print(f"[events] {getattr(fn, '__name__', 'write')} failed: {type(e).__name__}: {e}",
                      file=sys.stderr)


class DbWriter:
    """Writes runs and events through one lazily opened database connection."""

    def __init__(self, connect):
        self._connect = connect
        self._conn = None

    def _c(self):
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def start_run(self, run_id, trigger, sources):
        from . import db
        db.start_scrape_run(self._c(), run_id, trigger, sources)

    def add_events(self, events):
        from . import db
        db.add_events(self._c(), events)

    def finish_run(self, run_id, status, new_articles, summary):
        from . import db
        db.finish_scrape_run(self._c(), run_id, status, new_articles, summary)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None
