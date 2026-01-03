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

CREATE TABLE IF NOT EXISTS failed_files (
  file_path TEXT PRIMARY KEY,
  size_bytes INTEGER NOT NULL,
  first_failed_utc TEXT NOT NULL,
  last_failed_utc TEXT NOT NULL,
  failure_count INTEGER NOT NULL DEFAULT 1
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_ingested_files_size_bytes ON ingested_files(size_bytes);
CREATE INDEX IF NOT EXISTS idx_ingested_files_first_seen_utc ON ingested_files(first_seen_utc);
CREATE INDEX IF NOT EXISTS idx_uploads_local_sha256 ON uploads(local_sha256);
CREATE INDEX IF NOT EXISTS idx_uploads_uploaded_utc ON uploads(uploaded_utc);
CREATE INDEX IF NOT EXISTS idx_failed_files_size_bytes ON failed_files(size_bytes);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


