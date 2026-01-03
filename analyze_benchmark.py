#!/usr/bin/env python3
"""
Analyze benchmark results and identify bottlenecks.

Usage:
    python analyze_benchmark.py benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def analyze_results(results: dict) -> None:
    """Analyze benchmark results and print insights."""
    print("=" * 70)
    print("Benchmark Analysis - Bottleneck Identification")
    print("=" * 70)
    print()
    
    benchmarks = results.get("benchmarks", [])
    if not benchmarks:
        print("No benchmark results found.")
        return
    
    # Find slowest operations
    print("Slowest Operations (by total time):")
    print("-" * 70)
    sorted_by_total = sorted(benchmarks, key=lambda x: x.get("total", 0), reverse=True)
    for i, bench in enumerate(sorted_by_total[:5], 1):
        total = bench.get("total", 0)
        ops = bench.get("operations", 0)
        throughput = bench.get("throughput", 0)
        print(f"{i}. {bench['name']:45s} {total:8.3f}s  "
              f"({ops} ops, {throughput:.2f} ops/sec)")
    print()
    
    # Find operations with lowest throughput
    print("Lowest Throughput Operations:")
    print("-" * 70)
    sorted_by_throughput = sorted(
        [b for b in benchmarks if b.get("throughput", 0) > 0],
        key=lambda x: x.get("throughput", 0)
    )
    for i, bench in enumerate(sorted_by_throughput[:5], 1):
        throughput = bench.get("throughput", 0)
        mean = bench.get("mean", 0)
        print(f"{i}. {bench['name']:45s} {throughput:8.2f} ops/sec  "
              f"(mean: {mean:.3f}s per op)")
    print()
    
    # Compare sequential vs parallel
    print("Parallelization Analysis:")
    print("-" * 70)
    sequential_ops = {}
    parallel_ops = {}
    
    # Map benchmark names to their results
    for bench in benchmarks:
        name = bench["name"]
        # Match by the internal name (file_hashing, image_processing, etc.)
        if name.endswith("_parallel"):
            base_name = name.replace("_parallel", "")
            parallel_ops[base_name] = bench
        elif name not in ["database_queries", "file_copying", "file_scanning"]:
            # These are sequential operations
            sequential_ops[name] = bench
    
    # Also check display names for better matching
    for bench in benchmarks:
        display_name = bench.get("name", "")
        if "Sequential" in display_name:
            base_name = display_name.replace(" (Sequential)", "")
            sequential_ops[base_name] = bench
        elif "Parallel" in display_name:
            base_name = display_name.split(" (Parallel")[0]
            parallel_ops[base_name] = bench
    
    for base_name in set(list(sequential_ops.keys()) + list(parallel_ops.keys())):
        seq = sequential_ops.get(base_name)
        par = parallel_ops.get(base_name)
        
        if seq and par:
            seq_time = seq.get("total", 0)
            par_time = par.get("total", 0)
            speedup = seq_time / par_time if par_time > 0 else 0
            efficiency = speedup / par.get("metadata", {}).get("workers", 1)
            
            print(f"{base_name}:")
            print(f"  Sequential: {seq_time:.3f}s")
            print(f"  Parallel:   {par_time:.3f}s")
            print(f"  Speedup:    {speedup:.2f}x")
            print(f"  Efficiency: {efficiency:.2%}")
            if speedup < 1.0:
                print(f"  ⚠️  Parallel is SLOWER - overhead may be too high")
            elif speedup < 1.5:
                print(f"  ⚠️  Low speedup - may not be worth parallelization")
            print()
    
    # Database performance
    print("Database Performance:")
    print("-" * 70)
    db_bench = next((b for b in benchmarks if b["name"] == "database_queries"), None)
    if db_bench:
        mean = db_bench.get("mean", 0)
        throughput = db_bench.get("throughput", 0)
        size_query = db_bench.get("metadata", {}).get("size_query_time", 0)
        print(f"  Query mean time: {mean*1000:.3f}ms")
        print(f"  Query throughput: {throughput:.0f} queries/sec")
        if size_query > 0:
            print(f"  DISTINCT size_bytes query: {size_query*1000:.3f}ms")
            if size_query > 0.01:
                print(f"  ⚠️  DISTINCT query is slow - ensure index exists")
        print()
    
    # File I/O performance
    print("File I/O Performance:")
    print("-" * 70)
    hash_bench = next((b for b in benchmarks if b["name"] == "file_hashing"), None)
    copy_bench = next((b for b in benchmarks if b["name"] == "file_copying"), None)
    
    if hash_bench:
        hash_mean = hash_bench.get("mean", 0)
        hash_throughput = hash_bench.get("throughput", 0)
        print(f"  Hashing: {hash_mean:.3f}s per file, {hash_throughput:.2f} files/sec")
    
    if copy_bench:
        copy_mean = copy_bench.get("mean", 0)
        copy_throughput = copy_bench.get("throughput", 0)
        print(f"  Copying: {copy_mean:.3f}s per file, {copy_throughput:.2f} files/sec")
    
    if hash_bench and copy_bench:
        hash_mean = hash_bench.get("mean", 0)
        copy_mean = copy_bench.get("mean", 0)
        if hash_mean > copy_mean * 2:
            print(f"  ⚠️  Hashing is much slower than copying - consider optimizing")
    print()
    
    # Image processing performance
    print("Image Processing Performance:")
    print("-" * 70)
    img_bench = next((b for b in benchmarks if b["name"] == "image_processing"), None)
    if img_bench:
        img_mean = img_bench.get("mean", 0)
        img_throughput = img_bench.get("throughput", 0)
        print(f"  Processing: {img_mean:.3f}s per image, {img_throughput:.2f} images/sec")
        if img_mean > 0.1:
            print(f"  ⚠️  Image processing is slow - consider parallelization or optimization")
    print()
    
    # Recommendations
    print("=" * 70)
    print("Recommendations:")
    print("=" * 70)
    
    recommendations = []
    
    # Check for slow operations
    slow_ops = [b for b in benchmarks if b.get("mean", 0) > 0.1]
    if slow_ops:
        recommendations.append(
            f"  • {len(slow_ops)} operation(s) take >100ms each - consider optimization"
        )
    
    # Check parallelization efficiency
    for base_name in set(list(sequential_ops.keys()) + list(parallel_ops.keys())):
        seq = sequential_ops.get(base_name)
        par = parallel_ops.get(base_name)
        if seq and par:
            speedup = seq.get("total", 0) / par.get("total", 0) if par.get("total", 0) > 0 else 0
            if speedup < 1.0:
                recommendations.append(
                    f"  • {base_name}: Parallel version is slower - reduce overhead or increase workload"
                )
            elif speedup < 1.3:
                recommendations.append(
                    f"  • {base_name}: Low parallel speedup ({speedup:.2f}x) - may not be worth it"
                )
    
    # Check database performance
    if db_bench:
        size_query = db_bench.get("metadata", {}).get("size_query_time", 0)
        if size_query > 0.01:
            recommendations.append(
                "  • Database DISTINCT query is slow - verify indexes are being used"
            )
    
    # Check image processing
    if img_bench:
        img_mean = img_bench.get("mean", 0)
        if img_mean > 0.05:
            recommendations.append(
                "  • Image processing is slow - consider using more workers or optimizing PIL operations"
            )
    
    if recommendations:
        for rec in recommendations:
            print(rec)
    else:
        print("  ✓ No major bottlenecks identified!")
    print()


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument("results_file", type=Path, help="JSON file with benchmark results")
    args = parser.parse_args()
    
    if not args.results_file.exists():
        print(f"Error: Results file not found: {args.results_file}")
        return 1
    
    results = json.loads(args.results_file.read_text())
    analyze_results(results)
    return 0


if __name__ == "__main__":
    exit(main())

