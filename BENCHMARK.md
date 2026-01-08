# GhostRoll Performance Benchmarking

This directory contains tools for benchmarking GhostRoll performance and identifying bottlenecks.

## Tools

### `benchmark.py`

Runs comprehensive performance benchmarks on key GhostRoll operations:

- **File Hashing** (sequential and parallel) - SHA256 computation
- **Database Queries** - SQLite query performance with indexes
- **Image Processing** (sequential and parallel) - JPEG resizing and processing
- **File Copying** - File I/O operations
- **File Scanning** - Directory traversal performance

### `analyze_benchmark.py`

Analyzes benchmark results and provides:
- Slowest operations identification
- Throughput analysis
- Parallelization efficiency analysis
- Performance recommendations

## Usage

### Running Benchmarks

```bash
# Basic benchmark run
python benchmark.py

# Save results to JSON file
python benchmark.py --output results.json

# Run with profiling (shows top functions by time)
python benchmark.py --profile
```

### Analyzing Results

```bash
# Analyze benchmark results
python analyze_benchmark.py results.json
```

## Example Output

```
Benchmark Analysis - Bottleneck Identification
======================================================================

Slowest Operations (by total time):
----------------------------------------------------------------------
1. image_processing_parallel                        0.169s  (10 ops, 59.21 ops/sec)
2. image_processing                                 0.154s  (10 ops, 64.86 ops/sec)
3. file_hashing_parallel                            0.033s  (10 ops, 300.47 ops/sec)

Parallelization Analysis:
----------------------------------------------------------------------
image_processing:
  Sequential: 0.154s
  Parallel:   0.169s
  Speedup:    0.91x
  ⚠️  Parallel is SLOWER - overhead may be too high
```

## Interpreting Results

### Key Metrics

- **Total Time**: Total time for all operations
- **Throughput**: Operations per second
- **Mean/Median**: Average operation time
- **Speedup**: Parallel vs sequential speedup ratio

### Bottleneck Indicators

1. **Slow Operations**: Operations taking >100ms per item
2. **Low Throughput**: <10 ops/sec for I/O operations
3. **Poor Parallelization**: Parallel version slower than sequential
4. **Database Queries**: >10ms for simple queries (check indexes)

### Common Findings

- **Image Processing is Slow**: This is expected - JPEG processing is CPU-intensive
  - Solution: Use parallel processing with more workers for large batches
  - Consider: Optimize PIL operations or use faster image libraries

- **Parallel Overhead**: For small workloads (<20 files), parallel overhead may exceed benefits
  - Solution: Only use parallel processing for larger batches
  - Consider: Adjust worker count based on workload size

- **Database Queries Fast**: With proper indexes, queries should be <1ms
  - If slow: Verify indexes exist (`ghostroll/db.py`)

## Customizing Benchmarks

Edit `benchmark.py` to adjust:
- Number of test files/images
- File sizes
- Number of workers
- Test data complexity

## Integration with CI/CD

You can integrate benchmarks into CI/CD:

```bash
# Run benchmarks and check for regressions
python benchmark.py --output ci_results.json
python analyze_benchmark.py ci_results.json > benchmark_report.txt
```

## Performance Tips

Based on benchmark results:

1. **Use Parallel Processing** for:
   - Large batches (>50 files)
   - CPU-bound operations (image processing)
   - I/O-bound operations (hashing, copying)

2. **Use Sequential Processing** for:
   - Small batches (<20 files)
   - Operations with high overhead
   - When simplicity is preferred

3. **Database Optimization**:
   - Ensure indexes exist (see `ghostroll/db.py`)
   - Use batch queries instead of one-by-one
   - Consider connection pooling for high concurrency

4. **Image Processing**:
   - Parallel processing helps significantly for large batches
   - Consider worker count = CPU cores for CPU-bound work
   - Use fewer workers for I/O-bound operations



