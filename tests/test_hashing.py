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

