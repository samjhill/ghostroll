from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.hashing import sha256_file


def test_sha256_file(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    hash_hex, size = sha256_file(test_file)
    assert len(hash_hex) == 64  # SHA-256 hex digest length
    assert size == len("Hello, World!")
    assert isinstance(hash_hex, str)
    assert isinstance(size, int)


def test_sha256_file_empty(tmp_path: Path):
    test_file = tmp_path / "empty.txt"
    test_file.write_text("")

    hash_hex, size = sha256_file(test_file)
    assert len(hash_hex) == 64
    assert size == 0


def test_sha256_file_deterministic(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Same content")

    hash1, size1 = sha256_file(test_file)
    hash2, size2 = sha256_file(test_file)

    assert hash1 == hash2
    assert size1 == size2


def test_sha256_file_different_content(tmp_path: Path):
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("Content 1")
    file2.write_text("Content 2")

    hash1, _ = sha256_file(file1)
    hash2, _ = sha256_file(file2)

    assert hash1 != hash2


def test_sha256_file_large(tmp_path: Path):
    # Test with a larger file to ensure chunking works
    test_file = tmp_path / "large.txt"
    content = "x" * (2 * 1024 * 1024)  # 2MB
    test_file.write_text(content)

    hash_hex, size = sha256_file(test_file, chunk_size=1024 * 1024)
    assert len(hash_hex) == 64
    assert size == len(content)


def test_sha256_file_adaptive_chunk_size(tmp_path: Path):
    """Test that adaptive chunk size selection works correctly."""
    # Small file (<10MB) should use 1MB chunks
    small_file = tmp_path / "small.txt"
    small_file.write_text("x" * (5 * 1024 * 1024))  # 5MB
    hash1, _ = sha256_file(small_file)  # Should auto-select 1MB chunks
    hash1_explicit, _ = sha256_file(small_file, chunk_size=1024 * 1024)
    assert hash1 == hash1_explicit  # Same hash regardless of chunk size
    
    # Medium file (10-50MB) should use 4MB chunks
    medium_file = tmp_path / "medium.txt"
    medium_file.write_text("x" * (20 * 1024 * 1024))  # 20MB
    hash2, _ = sha256_file(medium_file)  # Should auto-select 4MB chunks
    hash2_explicit, _ = sha256_file(medium_file, chunk_size=4 * 1024 * 1024)
    assert hash2 == hash2_explicit
    
    # Large file (>50MB) should use 8MB chunks
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * (60 * 1024 * 1024))  # 60MB
    hash3, _ = sha256_file(large_file)  # Should auto-select 8MB chunks
    hash3_explicit, _ = sha256_file(large_file, chunk_size=8 * 1024 * 1024)
    assert hash3 == hash3_explicit

