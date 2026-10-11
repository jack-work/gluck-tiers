"""Per-user arrangements, on local disk.

sqlite, not Garage and not DuckDB. Garage 1.3.1 has no locking and no
versioning, so two savers clobber each other silently. DuckDB is single-writer
even for a read-only open, and one on this estate grew a 9.2 GB ledger because
nothing closed it. A connection here is opened per call and closed per call.
"""

import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS saves (
  user    TEXT NOT NULL,
  slug    TEXT NOT NULL,
  assign  TEXT NOT NULL,
  updated REAL NOT NULL,
  PRIMARY KEY (user, slug)
);
"""


class Store:
    def __init__(self, path):
        self.path = str(path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        # Bounded deliberately. The estate's one memory incident came from a
        # database sizing its cache against total RAM.
        c.execute("PRAGMA cache_size=-2000")
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def get(self, user, slug):
        c = self._conn()
        try:
            row = c.execute(
                "SELECT assign FROM saves WHERE user = ? AND slug = ?", (user, slug)
            ).fetchone()
        finally:
            c.close()
        return json.loads(row[0]) if row else {}

    def put(self, user, slug, assign):
        c = self._conn()
        try:
            c.execute(
                "INSERT INTO saves (user, slug, assign, updated) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (user, slug) DO UPDATE SET assign = excluded.assign, "
                "updated = excluded.updated",
                (user, slug, json.dumps(assign, sort_keys=True), time.time()),
            )
        finally:
            c.close()

    def users(self, slug):
        c = self._conn()
        try:
            return [r[0] for r in c.execute(
                "SELECT user FROM saves WHERE slug = ? ORDER BY user", (slug,)
            )]
        finally:
            c.close()
