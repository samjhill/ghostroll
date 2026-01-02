from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.db import connect


def test_db_connect_creates_schema(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)
    assert db_path.exists()

    # Check tables exist
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('ingested_files', 'uploads')"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert "ingested_files" in tables
    assert "uploads" in tables

    # Check schema
    cursor.execute("PRAGMA table_info(ingested_files)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "sha256" in columns
    assert "size_bytes" in columns
    assert "first_seen_utc" in columns

    cursor.execute("PRAGMA table_info(uploads)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "s3_key" in columns
    assert "local_sha256" in columns

    conn.close()


def test_db_row_factory(tmp_path: Path):
    db_path = tmp_path / "test.db"
    conn = connect(db_path)

    cursor = conn.cursor()
    cursor.execute("INSERT INTO ingested_files (sha256, size_bytes, first_seen_utc) VALUES (?, ?, ?)", ("abc123", 1024, "2024-01-01T00:00:00Z"))
    conn.commit()

    cursor.execute("SELECT * FROM ingested_files WHERE sha256 = ?", ("abc123",))
    row = cursor.fetchone()
    assert row is not None
    # Row factory should make it accessible by name
    assert row["sha256"] == "abc123"
    assert row["size_bytes"] == 1024

    conn.close()


def test_db_indexes_created(tmp_path: Path):
    """Verify that performance indexes are created."""
    db_path = tmp_path / "test.db"
    conn = connect(db_path)

    cursor = conn.cursor()
    # Check that indexes exist
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    )
    indexes = {row[0] for row in cursor.fetchall()}

    # Verify expected indexes exist
    expected_indexes = {
        "idx_ingested_files_size_bytes",
        "idx_ingested_files_first_seen_utc",
        "idx_uploads_local_sha256",
        "idx_uploads_uploaded_utc",
    }
    assert expected_indexes.issubset(indexes), f"Missing indexes. Found: {indexes}"

    conn.close()

