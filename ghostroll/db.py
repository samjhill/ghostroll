from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS ingested_files (
  sha256 TEXT PRIMARY KEY,
  size_bytes INTEGER NOT NULL,
  first_seen_utc TEXT NOT NULL,
  source_hint TEXT
);

CREATE TABLE IF NOT EXISTS uploads (
  s3_key TEXT PRIMARY KEY,
  local_sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  uploaded_utc TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


