from __future__ import annotations

from pathlib import Path

import pytest

from ghostroll.media import is_jpeg, is_media, is_raw


def test_is_jpeg():
    assert is_jpeg(Path("test.jpg"))
    assert is_jpeg(Path("test.JPG"))
    assert is_jpeg(Path("test.jpeg"))
    assert is_jpeg(Path("test.JPEG"))
    assert not is_jpeg(Path("test.png"))
    assert not is_jpeg(Path("test.txt"))


def test_is_raw():
    assert is_raw(Path("test.arw"))
    assert is_raw(Path("test.cr2"))
    assert is_raw(Path("test.cr3"))
    assert is_raw(Path("test.nef"))
    assert is_raw(Path("test.dng"))
    assert is_raw(Path("test.raf"))
    assert is_raw(Path("test.rw2"))
    assert not is_raw(Path("test.jpg"))
    assert not is_raw(Path("test.png"))


def test_is_media():
    assert is_media(Path("test.jpg"))
    assert is_media(Path("test.jpeg"))
    assert is_media(Path("test.arw"))
    assert is_media(Path("test.cr2"))
    assert is_media(Path("test.dng"))
    assert not is_media(Path("test.png"))
    assert not is_media(Path("test.txt"))
    assert not is_media(Path("test"))


def test_case_insensitive():
    assert is_jpeg(Path("TEST.JPG"))
    assert is_raw(Path("TEST.ARW"))
    assert is_media(Path("TEST.JPG"))
    assert is_media(Path("TEST.ARW"))

