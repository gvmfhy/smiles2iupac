"""SQLite cache for canonical SMILES → IUPAC name."""

import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path.home() / ".smiles2iupac" / "cache.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    canonical_smiles TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source ON names(source);
"""


class Cache:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)

    def lookup(self, canonical_smiles: str) -> tuple[str, str, float] | None:
        cur = self._conn.execute(
            "SELECT name, source, confidence FROM names WHERE canonical_smiles = ?",
            (canonical_smiles,),
        )
        row = cur.fetchone()
        return tuple(row) if row else None

    def store(
        self, canonical_smiles: str, name: str, source: str, confidence: float
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO names VALUES (?, ?, ?, ?, ?)",
            (canonical_smiles, name, source, confidence, time.time()),
        )
        self._conn.commit()

    def size(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM names")
        return cur.fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
