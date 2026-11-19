"""Pamti sta je vec uvezeno -> prekinut uvoz se samo pokrene ponovo, bez duplikata."""
from __future__ import annotations

import sqlite3
import threading
import time


class State:
    def __init__(self, path: str | None):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS uploaded (
            key TEXT PRIMARY KEY, folder TEXT, origin TEXT, size INTEGER, ts REAL)""")
        self.db.commit()
        self._pending = 0

    @staticmethod
    def key(content_hash: str, folder: str) -> str:
        return content_hash + "|" + folder.lower()

    def done(self, key: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM uploaded WHERE key=?", (key,)).fetchone() is not None

    def mark(self, key: str, folder: str, origin: str, size: int):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO uploaded VALUES (?,?,?,?,?)",
                            (key, folder, origin, size, time.time()))
            self._pending += 1
            if self._pending >= 50:
                self.db.commit()
                self._pending = 0

    def close(self):
        with self.lock:
            self.db.commit()
            self.db.close()
