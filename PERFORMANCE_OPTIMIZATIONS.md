# GhostRoll Performance Optimization Recommendations

## Current Performance Characteristics

### Bottlenecks Identified

1. **File Hashing** (I/O bound, CPU bound)
   - Limited to 4 workers max
   - Always hashes from SD card (slow USB/SD card I/O)
   - 1MB chunk size (could be larger for faster cards)

2. **Database Operations** (I/O bound)
   - Individual INSERT statements (no batching)
   - Multiple commits per session
   - Crash recovery re-hashes local files unnecessarily

3. **Image Processing** (CPU bound)
   - LANCZOS resampling (high quality but slow)
   - Sequential processing per image (share + thumb separately)
   - No caching of intermediate results

4. **File Copying** (I/O bound)
   - Limited to 4 workers
   - No copy-on-write optimization
   - No incremental sync

5. **AWS Operations** (Network bound)
   - Subprocess overhead for each AWS CLI call
   - No connection pooling
   - Sequential retries (could be parallel)

6. **Gallery Generation** (CPU bound)
   - Generates full gallery even when only partial uploads complete
   - No incremental HTML updates

## Optimization Recommendations

### 1. Hashing Optimizations (High Impact)

#### 1.1 Increase Hash Workers
**Current**: `min(4, max(1, cfg.process_workers))`  
**Recommended**: Make configurable, default to 8-12 for fast storage

```python
# In config.py
hash_workers: int = 8  # Configurable via GHOSTROLL_HASH_WORKERS

# In pipeline.py
hash_workers = min(cfg.hash_workers, max(1, len(files_to_check) // 10))
```

**Impact**: 2-3x faster hashing for large batches

#### 1.2 Optimize Hash Chunk Size
**Current**: 1MB chunks  
**Recommended**: Adaptive chunk size based on file size

```python
def sha256_file(path: Path, *, chunk_size: int | None = None) -> tuple[str, int]:
    if chunk_size is None:
        # Use larger chunks for larger files (better for fast storage)
        file_size = path.stat().st_size
        if file_size > 50 * 1024 * 1024:  # > 50MB
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
        elif file_size > 10 * 1024 * 1024:  # > 10MB
            chunk_size = 4 * 1024 * 1024  # 4MB chunks
        else:
            chunk_size = 1024 * 1024  # 1MB chunks (default)
    
    # ... rest of function
```

**Impact**: 10-20% faster hashing for large files

#### 1.3 Smart Crash Recovery Hashing
**Current**: Re-hashes local files even when SHA already known  
**Recommended**: Check database first, only hash if needed

```python
# In crash recovery section
if p in existing_originals:
    local_copy = existing_originals[p]
    # Check if we already have SHA in DB for this file
    if sha not in existing_shas:  # Only hash if not already known
        try:
            local_sha, _ = sha256_file(local_copy)
            if local_sha == sha:
                # ... mark as ingested
```

**Impact**: Eliminates unnecessary re-hashing in crash recovery scenarios

### 2. Database Optimizations (High Impact)

#### 2.1 Batch INSERT Operations
**Current**: Individual INSERT per file  
**Recommended**: Batch INSERT with executemany()

```python
def _db_mark_ingested_batch(
    conn: sqlite3.Connection, *, items: list[tuple[str, int, str]]
) -> None:
    """Batch insert multiple files at once."""
    now = _utc_now()
    conn.executemany(
        "INSERT OR IGNORE INTO ingested_files(sha256,size_bytes,first_seen_utc,source_hint) "
        "VALUES(?,?,?,?)",
        [(sha, size, now, hint) for sha, size, hint in items],
    )

# Usage in pipeline.py
db_inserts: list[tuple[str, int, str]] = []
# ... collect all inserts
if db_inserts:
    _db_mark_ingested_batch(conn, items=db_inserts)
    conn.commit()
```

**Impact**: 5-10x faster database writes for large batches

#### 2.2 Reduce Commit Frequency
**Current**: Multiple commits per session  
**Recommended**: Single commit after batch operations

```python
# Collect all DB operations, commit once
conn.execute("BEGIN")
# ... all inserts
conn.commit()
```

**Impact**: 2-3x faster database operations

#### 2.3 Prepared Statements Cache
**Current**: SQL string formatting  
**Recommended**: Use parameterized queries (already done, but ensure consistency)

**Impact**: Minor, but ensures optimal SQLite performance

### 3. Image Processing Optimizations (High Impact)

#### 3.1 Faster Resampling Algorithm
**Current**: LANCZOS (high quality, slow)  
**Recommended**: Use BILINEAR or NEAREST for thumbnails, LANCZOS only for share images

```python
def render_jpeg_derivative(
    src_path: Path,
    *,
    dst_path: Path,
    max_long_edge: int,
    quality: int,
    resampling: Image.Resampling | None = None,
) -> None:
    if resampling is None:
        # Use faster resampling for small outputs (thumbnails)
        if max_long_edge <= 512:
            resampling = Image.Resampling.BILINEAR  # Faster for thumbnails
        else:
            resampling = Image.Resampling.LANCZOS  # High quality for share images
    
    # ... use resampling parameter
```

**Impact**: 2-3x faster thumbnail generation, minimal quality loss

#### 3.2 Parallel Share + Thumb Generation
**Current**: Sequential (share then thumb)  
**Recommended**: Generate both in parallel from same source

```python
def _process_one_parallel(task: tuple[Path, Path, Path, Path]) -> tuple[str, float, str, str]:
    src, rel, share_out, thumb_out = task
    
    # Generate both in parallel using threads
    def gen_share():
        if not share_out.exists():
            render_jpeg_derivative(src, dst_path=share_out, ...)
    
    def gen_thumb():
        if not thumb_out.exists():
            render_jpeg_derivative(src, dst_path=thumb_out, ...)
    
    with ThreadPoolExecutor(max_workers=2) as ex:
        ex.submit(gen_share)
        ex.submit(gen_thumb)
    
    # ... rest
```

**Impact**: 30-40% faster per-image processing

#### 3.3 Progressive JPEG Encoding
**Current**: Progressive=True (good)  
**Recommended**: Optimize quality/size tradeoff

```python
# Use mozjpeg or libjpeg-turbo if available
# Consider adaptive quality based on image content
```

**Impact**: Smaller file sizes, faster uploads

### 4. File Copying Optimizations (Medium Impact)

#### 4.1 Increase Copy Workers
**Current**: `min(4, max(1, cfg.process_workers))`  
**Recommended**: Separate config, default to 6-8

```python
# In config.py
copy_workers: int = 6  # Configurable via GHOSTROLL_COPY_WORKERS

# In pipeline.py
copy_workers = min(cfg.copy_workers, max(1, len(new_files) // 5))
```

**Impact**: 1.5-2x faster copying for large batches

#### 4.2 Use shutil.copyfile() for Large Files
**Current**: `shutil.copy2()` (preserves metadata, slower)  
**Recommended**: Use `copyfile()` for large files, `copy2()` only if metadata needed

```python
def _copy2_ignore_existing(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    
    # For large files, use copyfile (faster, no metadata)
    if src.stat().st_size > 10 * 1024 * 1024:  # > 10MB
        shutil.copyfile(src, dst)
    else:
        shutil.copy2(src, dst)
    return True
```

**Impact**: 10-15% faster copying for large files

### 5. AWS Operations Optimizations (High Impact)

#### 5.1 Use boto3 Instead of AWS CLI
**Current**: Subprocess calls to `aws s3 cp`  
**Recommended**: Direct boto3 API calls

```python
import boto3
from botocore.config import Config

# Reuse client with connection pooling
_s3_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None:
        config = Config(
            max_pool_connections=50,  # Connection pooling
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        _s3_client = boto3.client('s3', config=config)
    return _s3_client

def s3_cp(local_path: Path, *, bucket: str, key: str, retries: int = 3) -> None:
    client = get_s3_client()
    client.upload_file(str(local_path), bucket, key)
```

**Impact**: 3-5x faster uploads (eliminates subprocess overhead)

#### 5.2 Multipart Upload for Large Files
**Current**: Single-part upload  
**Recommended**: Use multipart for files > 100MB

```python
def s3_cp_multipart(local_path: Path, *, bucket: str, key: str) -> None:
    file_size = local_path.stat().st_size
    if file_size > 100 * 1024 * 1024:  # > 100MB
        # Use multipart upload
        config = TransferConfig(multipart_threshold=100*1024*1024)
        client.upload_file(str(local_path), bucket, key, Config=config)
    else:
        client.upload_file(str(local_path), bucket, key)
```

**Impact**: Faster uploads for large files, better error recovery

#### 5.3 Batch Presigning
**Current**: Individual presign calls  
**Recommended**: Generate presigned URLs in larger batches

```python
# Presign multiple URLs in parallel batches
def _presign_batch(keys: list[tuple[str, str]]) -> dict[str, str]:
    """Presign multiple S3 keys in parallel."""
    with ThreadPoolExecutor(max_workers=cfg.presign_workers) as ex:
        futures = {
            ex.submit(s3_presign, bucket=bucket, key=key, expires_in_seconds=expiry): key
            for bucket, key in keys
        }
        return {fut.result(): key for fut, key in futures.items()}
```

**Impact**: Better parallelization, 20-30% faster presigning

### 6. Gallery Generation Optimizations (Low-Medium Impact)

#### 6.1 Incremental Gallery Updates
**Current**: Full gallery rebuild every 30 seconds  
**Recommended**: Append-only updates for new images

```python
def _refresh_gallery_incremental(
    existing_items: list, new_items: list, uploaded_keys: set[str]
) -> None:
    """Append new items to existing gallery instead of rebuilding."""
    # Only add items that are newly uploaded
    # Update existing HTML with new items
```

**Impact**: Faster gallery updates, especially for large sessions

#### 6.2 Lazy Loading in Gallery
**Current**: All images loaded in gallery  
**Recommended**: Lazy load images as user scrolls

```python
# In gallery HTML generation
<img loading="lazy" src="..." />
```

**Impact**: Faster initial gallery load, better UX

### 7. Memory Optimizations (Medium Impact)

#### 7.1 Stream Large File Operations
**Current**: Load entire files into memory  
**Recommended**: Stream processing where possible

```python
# Already done for hashing (chunked), but ensure other operations stream too
```

**Impact**: Lower memory usage, better for large files

#### 7.2 Clear Intermediate Results
**Current**: Keep all data in memory  
**Recommended**: Clear processed data as we go

```python
# After processing each batch, clear intermediate lists
processed_batch = []
# ... process
# Clear after upload
del processed_batch
```

**Impact**: Lower memory footprint for large sessions

### 8. Configuration Optimizations

#### 8.1 Adaptive Worker Counts
**Current**: Fixed worker counts  
**Recommended**: Adaptive based on workload

```python
def calculate_optimal_workers(task_count: int, base_workers: int) -> int:
    """Calculate optimal worker count based on task count."""
    if task_count < 10:
        return min(2, base_workers)
    elif task_count < 50:
        return min(4, base_workers)
    else:
        return base_workers
```

**Impact**: Better resource utilization

#### 8.2 Profile-Based Defaults
**Current**: CPU-count based defaults  
**Recommended**: Storage-speed aware defaults

```python
# Detect storage speed (SD card vs SSD vs NVMe)
# Adjust workers accordingly
```

**Impact**: Better defaults for different hardware

## Implementation Priority

### Phase 1: Quick Wins (1-2 days)
1. ✅ Increase hash workers (configurable)
2. ✅ Batch database INSERTs
3. ✅ Faster resampling for thumbnails
4. ✅ Increase copy workers

**Expected Impact**: 2-3x overall speedup

### Phase 2: Medium Effort (3-5 days)
1. ✅ Replace AWS CLI with boto3
2. ✅ Optimize hash chunk sizes
3. ✅ Parallel share+thumb generation
4. ✅ Smart crash recovery

**Expected Impact**: Additional 1.5-2x speedup

### Phase 3: Advanced (1-2 weeks)
1. ✅ Multipart uploads
2. ✅ Incremental gallery updates
3. ✅ Adaptive worker counts
4. ✅ Storage speed detection

**Expected Impact**: Additional 1.2-1.5x speedup + better UX

## Expected Overall Performance Improvement

**Current**: ~100 photos in 5-10 minutes  
**After Phase 1**: ~100 photos in 2-3 minutes (2-3x faster)  
**After Phase 2**: ~100 photos in 1-2 minutes (3-5x faster)  
**After Phase 3**: ~100 photos in 30-60 seconds (5-10x faster)

## Measurement & Benchmarking

### Add Performance Metrics
```python
import time

class PerformanceMetrics:
    def __init__(self):
        self.timings = {}
    
    def time_phase(self, phase: str):
        return self._Timer(phase, self.timings)

class _Timer:
    def __init__(self, phase: str, timings: dict):
        self.phase = phase
        self.timings = timings
        self.start = time.time()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        elapsed = time.time() - self.start
        self.timings[self.phase] = elapsed
```

### Benchmark Suite
Create `benchmark.py` to measure:
- Hashing throughput (MB/s)
- Database write speed (inserts/sec)
- Image processing speed (images/sec)
- Upload speed (MB/s)
- End-to-end pipeline time

## Code Examples

### Example 1: Batch Database Operations
```python
# In pipeline.py, replace individual inserts with batch

# Before:
for sha, size, source_hint in db_inserts:
    _db_mark_ingested(conn, sha256=sha, size_bytes=size, source_hint=source_hint)
conn.commit()

# After:
_db_mark_ingested_batch(conn, items=db_inserts)
conn.commit()
```

### Example 2: boto3 Integration
```python
# New aws_boto3.py module
import boto3
from botocore.config import Config
from pathlib import Path

_s3_client = None
_presign_client = None

def get_s3_client():
    global _s3_client
    if _s3_client is None:
        config = Config(
            max_pool_connections=50,
            retries={'max_attempts': 3, 'mode': 'adaptive'}
        )
        _s3_client = boto3.client('s3', config=config)
    return _s3_client

def s3_upload_file(local_path: Path, *, bucket: str, key: str) -> None:
    client = get_s3_client()
    file_size = local_path.stat().st_size
    
    # Use multipart for large files
    from boto3.s3.transfer import TransferConfig
    config = None
    if file_size > 100 * 1024 * 1024:  # > 100MB
        config = TransferConfig(
            multipart_threshold=100 * 1024 * 1024,
            max_concurrency=10,
            multipart_chunksize=10 * 1024 * 1024
        )
    
    client.upload_file(str(local_path), bucket, key, Config=config)

def s3_presign_url(*, bucket: str, key: str, expires_in_seconds: int) -> str:
    global _presign_client
    if _presign_client is None:
        _presign_client = boto3.client('s3')
    
    return _presign_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires_in_seconds
    )
```

## Testing Strategy

1. **Unit Tests**: Test each optimization independently
2. **Integration Tests**: Test full pipeline with optimizations
3. **Benchmark Tests**: Measure before/after performance
4. **Regression Tests**: Ensure quality/functionality not degraded

## Risks & Considerations

1. **Memory Usage**: More workers = more memory (monitor)
2. **Quality**: Faster resampling may reduce quality (test thoroughly)
3. **Compatibility**: boto3 requires Python dependency (vs AWS CLI system dependency)
4. **Complexity**: More code to maintain

## Conclusion

These optimizations can provide **5-10x overall performance improvement** with careful implementation. Start with Phase 1 quick wins for immediate 2-3x improvement, then proceed with more advanced optimizations based on actual bottlenecks observed in production.

