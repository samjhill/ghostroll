#!/usr/bin/env python3
"""
Benchmark script to identify performance bottlenecks in GhostRoll.

Usage:
    python benchmark.py [--profile] [--output results.json]
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import shutil
import sqlite3
import statistics
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image

# Import GhostRoll modules
from ghostroll.db import connect
from ghostroll.hashing import sha256_file
from ghostroll.image_processing import render_jpeg_derivative


class BenchmarkResult:
    """Container for benchmark results."""
    
    def __init__(self, name: str):
        self.name = name
        self.times: list[float] = []
        self.total_time: float = 0.0
        self.operations: int = 0
        self.throughput: float = 0.0
        self.metadata: dict[str, Any] = {}
    
    def add_time(self, elapsed: float, operations: int = 1):
        """Record a timing."""
        self.times.append(elapsed)
        self.total_time += elapsed
        self.operations += operations
    
    def finalize(self):
        """Calculate statistics."""
        if self.times:
            self.metadata = {
                "mean": statistics.mean(self.times),
                "median": statistics.median(self.times),
                "stdev": statistics.stdev(self.times) if len(self.times) > 1 else 0.0,
                "min": min(self.times),
                "max": max(self.times),
                "total": self.total_time,
                "operations": self.operations,
            }
            if self.total_time > 0:
                self.throughput = self.operations / self.total_time
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            **self.metadata,
            "throughput": self.throughput,
        }


def benchmark_file_hashing(num_files: int = 10, file_size_mb: float = 5.0) -> BenchmarkResult:
    """Benchmark SHA256 file hashing."""
    result = BenchmarkResult("file_hashing")
    result.metadata["num_files"] = num_files
    result.metadata["file_size_mb"] = file_size_mb
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_files = []
        
        # Create test files
        print(f"  Creating {num_files} test files ({file_size_mb}MB each)...")
        file_size = int(file_size_mb * 1024 * 1024)
        for i in range(num_files):
            test_file = tmp_path / f"test_{i}.bin"
            with test_file.open("wb") as f:
                f.write(os.urandom(file_size))
            test_files.append(test_file)
        
        # Benchmark hashing
        print(f"  Hashing {num_files} files...")
        start = time.perf_counter()
        for test_file in test_files:
            file_start = time.perf_counter()
            sha256_file(test_file)
            file_elapsed = time.perf_counter() - file_start
            result.add_time(file_elapsed)
        total_elapsed = time.perf_counter() - start
        result.metadata["total_elapsed"] = total_elapsed
    
    result.finalize()
    return result


def benchmark_file_hashing_parallel(num_files: int = 10, file_size_mb: float = 5.0, workers: int = 4) -> BenchmarkResult:
    """Benchmark parallel SHA256 file hashing."""
    result = BenchmarkResult("file_hashing_parallel")
    result.metadata["num_files"] = num_files
    result.metadata["file_size_mb"] = file_size_mb
    result.metadata["workers"] = workers
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_files = []
        
        # Create test files
        print(f"  Creating {num_files} test files ({file_size_mb}MB each)...")
        file_size = int(file_size_mb * 1024 * 1024)
        for i in range(num_files):
            test_file = tmp_path / f"test_{i}.bin"
            with test_file.open("wb") as f:
                f.write(os.urandom(file_size))
            test_files.append(test_file)
        
        # Benchmark parallel hashing
        print(f"  Hashing {num_files} files in parallel ({workers} workers)...")
        start = time.perf_counter()
        
        def hash_one(path: Path) -> float:
            file_start = time.perf_counter()
            sha256_file(path)
            return time.perf_counter() - file_start
        
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(hash_one, f): f for f in test_files}
            for fut in as_completed(futures):
                elapsed = fut.result()
                result.add_time(elapsed)
        
        total_elapsed = time.perf_counter() - start
        result.metadata["total_elapsed"] = total_elapsed
    
    result.finalize()
    return result


def benchmark_database_queries(num_records: int = 1000, num_queries: int = 100) -> BenchmarkResult:
    """Benchmark database queries with indexes."""
    result = BenchmarkResult("database_queries")
    result.metadata["num_records"] = num_records
    result.metadata["num_queries"] = num_queries
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    
    try:
        # Create database with schema
        conn = connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ingested_files (
              sha256 TEXT PRIMARY KEY,
              size_bytes INTEGER NOT NULL,
              first_seen_utc TEXT NOT NULL,
              source_hint TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ingested_files_size_bytes ON ingested_files(size_bytes);
        """)
        
        # Insert test data
        print(f"  Inserting {num_records} records...")
        start = time.perf_counter()
        for i in range(num_records):
            conn.execute(
                "INSERT INTO ingested_files(sha256, size_bytes, first_seen_utc) VALUES(?, ?, ?)",
                (f"sha256_{i:06d}", 1024 * (i + 1), "2024-01-01T00:00:00Z")
            )
        conn.commit()
        insert_time = time.perf_counter() - start
        result.metadata["insert_time"] = insert_time
        
        # Benchmark queries
        print(f"  Running {num_queries} queries...")
        query_times = []
        for i in range(num_queries):
            query_start = time.perf_counter()
            # Simulate the duplicate check query
            conn.execute(
                "SELECT sha256 FROM ingested_files WHERE sha256 IN (?, ?, ?, ?, ?)",
                (f"sha256_{i:06d}", f"sha256_{i+1:06d}", f"sha256_{i+2:06d}", 
                 f"sha256_{i+3:06d}", f"sha256_{i+4:06d}")
            ).fetchall()
            query_elapsed = time.perf_counter() - query_start
            query_times.append(query_elapsed)
            result.add_time(query_elapsed)
        
        # Benchmark size-based query (used in _db_get_known_sizes)
        print("  Running DISTINCT size_bytes query...")
        size_query_start = time.perf_counter()
        conn.execute("SELECT DISTINCT size_bytes FROM ingested_files").fetchall()
        size_query_elapsed = time.perf_counter() - size_query_start
        result.metadata["size_query_time"] = size_query_elapsed
        
        conn.close()
    finally:
        db_path.unlink()
    
    result.finalize()
    return result


def benchmark_image_processing(num_images: int = 10) -> BenchmarkResult:
    """Benchmark JPEG image processing (resize, orient, strip metadata)."""
    result = BenchmarkResult("image_processing")
    result.metadata["num_images"] = num_images
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        
        # Create test JPEG images
        print(f"  Creating {num_images} test JPEG images...")
        test_images = []
        for i in range(num_images):
            # Create a test image (1920x1080)
            img = Image.new("RGB", (1920, 1080), color=(i % 255, (i * 2) % 255, (i * 3) % 255))
            test_file = src_dir / f"test_{i}.jpg"
            img.save(test_file, "JPEG", quality=95)
            test_images.append(test_file)
        
        # Benchmark processing
        print(f"  Processing {num_images} images...")
        for test_file in test_images:
            dst_file = dst_dir / test_file.name
            proc_start = time.perf_counter()
            render_jpeg_derivative(
                test_file,
                dst_path=dst_file,
                max_long_edge=2048,
                quality=90,
            )
            proc_elapsed = time.perf_counter() - proc_start
            result.add_time(proc_elapsed)
    
    result.finalize()
    return result


def benchmark_image_processing_parallel(num_images: int = 10, workers: int = 4) -> BenchmarkResult:
    """Benchmark parallel image processing."""
    result = BenchmarkResult("image_processing_parallel")
    result.metadata["num_images"] = num_images
    result.metadata["workers"] = workers
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        
        # Create test JPEG images
        print(f"  Creating {num_images} test JPEG images...")
        test_images = []
        for i in range(num_images):
            img = Image.new("RGB", (1920, 1080), color=(i % 255, (i * 2) % 255, (i * 3) % 255))
            test_file = src_dir / f"test_{i}.jpg"
            img.save(test_file, "JPEG", quality=95)
            test_images.append(test_file)
        
        # Benchmark parallel processing
        print(f"  Processing {num_images} images in parallel ({workers} workers)...")
        
        def process_one(src: Path) -> float:
            dst = dst_dir / src.name
            proc_start = time.perf_counter()
            render_jpeg_derivative(
                src,
                dst_path=dst,
                max_long_edge=2048,
                quality=90,
            )
            return time.perf_counter() - proc_start
        
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(process_one, img): img for img in test_images}
            for fut in as_completed(futures):
                elapsed = fut.result()
                result.add_time(elapsed)
    
    result.finalize()
    return result


def benchmark_file_copying(num_files: int = 10, file_size_mb: float = 5.0) -> BenchmarkResult:
    """Benchmark file copying operations."""
    result = BenchmarkResult("file_copying")
    result.metadata["num_files"] = num_files
    result.metadata["file_size_mb"] = file_size_mb
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        
        # Create test files
        print(f"  Creating {num_files} test files ({file_size_mb}MB each)...")
        file_size = int(file_size_mb * 1024 * 1024)
        test_files = []
        for i in range(num_files):
            test_file = src_dir / f"test_{i}.bin"
            with test_file.open("wb") as f:
                f.write(os.urandom(file_size))
            test_files.append(test_file)
        
        # Benchmark copying
        print(f"  Copying {num_files} files...")
        for test_file in test_files:
            dst_file = dst_dir / test_file.name
            copy_start = time.perf_counter()
            shutil.copy2(test_file, dst_file)
            copy_elapsed = time.perf_counter() - copy_start
            result.add_time(copy_elapsed)
    
    result.finalize()
    return result


def benchmark_file_scanning(num_files: int = 100, depth: int = 3) -> BenchmarkResult:
    """Benchmark file system scanning (simulating DCIM directory scan)."""
    result = BenchmarkResult("file_scanning")
    result.metadata["num_files"] = num_files
    result.metadata["depth"] = depth
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # Create directory structure
        print(f"  Creating directory structure with {num_files} files (depth {depth})...")
        files_created = 0
        for d in range(depth):
            dir_path = tmp_path
            for i in range(d):
                dir_path = dir_path / f"dir_{i}"
            dir_path.mkdir(parents=True, exist_ok=True)
            
            files_per_dir = num_files // depth
            for i in range(files_per_dir):
                test_file = dir_path / f"IMG_{files_created:04d}.JPG"
                # Create a small dummy file
                test_file.write_bytes(b"dummy image data")
                files_created += 1
        
        # Benchmark scanning with find command (like the pipeline does)
        print("  Scanning with 'find' command...")
        scan_start = time.perf_counter()
        result_find = subprocess.run(
            ["find", str(tmp_path), "-type", "f"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        scan_elapsed = time.perf_counter() - scan_start
        result.add_time(scan_elapsed, operations=len(result_find.stdout.splitlines()))
        result.metadata["find_time"] = scan_elapsed
        
        # Benchmark scanning with os.walk (fallback method)
        print("  Scanning with os.walk (fallback)...")
        import os
        scan_start = time.perf_counter()
        file_count = 0
        for root, dirs, files in os.walk(str(tmp_path)):
            file_count += len(files)
        scan_elapsed = time.perf_counter() - scan_start
        result.metadata["os_walk_time"] = scan_elapsed
        result.metadata["files_found"] = file_count
    
    result.finalize()
    return result


def run_all_benchmarks(profile: bool = False) -> dict[str, Any]:
    """Run all benchmarks and return results."""
    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "benchmarks": [],
    }
    
    benchmarks = [
        ("File Hashing (Sequential)", lambda: benchmark_file_hashing(10, 5.0)),
        ("File Hashing (Parallel, 4 workers)", lambda: benchmark_file_hashing_parallel(10, 5.0, 4)),
        ("Database Queries", lambda: benchmark_database_queries(1000, 100)),
        ("Image Processing (Sequential)", lambda: benchmark_image_processing(10)),
        ("Image Processing (Parallel, 4 workers)", lambda: benchmark_image_processing_parallel(10, 4)),
        ("File Copying", lambda: benchmark_file_copying(10, 5.0)),
        ("File Scanning", lambda: benchmark_file_scanning(100, 3)),
    ]
    
    for name, benchmark_fn in benchmarks:
        print(f"\n{'='*60}")
        print(f"Benchmark: {name}")
        print(f"{'='*60}")
        
        if profile:
            profiler = cProfile.Profile()
            profiler.enable()
        
        try:
            result = benchmark_fn()
            result.finalize()
            results["benchmarks"].append(result.to_dict())
            
            print(f"\nResults for {name}:")
            print(f"  Total time: {result.total_time:.3f}s")
            print(f"  Operations: {result.operations}")
            if result.throughput > 0:
                print(f"  Throughput: {result.throughput:.2f} ops/sec")
            if result.metadata.get("mean"):
                print(f"  Mean: {result.metadata['mean']:.3f}s")
                print(f"  Median: {result.metadata['median']:.3f}s")
                print(f"  Min: {result.metadata['min']:.3f}s")
                print(f"  Max: {result.metadata['max']:.3f}s")
        
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        if profile:
            profiler.disable()
            stats = pstats.Stats(profiler)
            stats.sort_stats("cumulative")
            print(f"\n  Top 10 functions by cumulative time:")
            stats.print_stats(10)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Benchmark GhostRoll performance")
    parser.add_argument("--profile", action="store_true", help="Enable profiling")
    parser.add_argument("--output", type=Path, help="Output JSON file for results")
    args = parser.parse_args()
    
    print("GhostRoll Performance Benchmark")
    print("=" * 60)
    
    results = run_all_benchmarks(profile=args.profile)
    
    if args.output:
        args.output.write_text(json.dumps(results, indent=2))
        print(f"\nResults saved to: {args.output}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for bench in results["benchmarks"]:
        print(f"{bench['name']:40s} {bench.get('total', 0):8.3f}s  "
              f"({bench.get('operations', 0)} ops, "
              f"{bench.get('throughput', 0):.2f} ops/sec)")


if __name__ == "__main__":
    main()



