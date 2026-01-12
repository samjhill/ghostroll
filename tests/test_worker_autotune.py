from __future__ import annotations

from ghostroll.pipeline import _auto_tune_process_workers


def test_auto_tune_no_meminfo_keeps_requested() -> None:
    assert _auto_tune_process_workers(requested=4, mem_available_bytes=None) == 4


def test_auto_tune_clamps_to_one_when_low_mem() -> None:
    # 300MB available, usable 60% => 180MB, per worker 220MB => only 1 allowed.
    mem = 300 * 1024 * 1024
    assert _auto_tune_process_workers(requested=4, mem_available_bytes=mem, per_worker_mb=220, max_fraction=0.60) == 1


def test_auto_tune_allows_more_when_mem_is_high() -> None:
    # 2GB available, usable 60% => 1.2GB, per worker 200MB => 6 allowed, so requested 4 remains.
    mem = 2 * 1024 * 1024 * 1024
    assert _auto_tune_process_workers(requested=4, mem_available_bytes=mem, per_worker_mb=200, max_fraction=0.60) == 4

