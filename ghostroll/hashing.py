from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, *, chunk_size: int | None = None) -> tuple[str, int]:
    """Compute SHA-256 hash of a file.
    
    Args:
        path: File path to hash
        chunk_size: Chunk size in bytes. If None, automatically selects based on file size:
            - >50MB: 8MB chunks (better for fast storage)
            - >10MB: 4MB chunks
            - Otherwise: 1MB chunks (default)
    
    Returns:
        Tuple of (hex digest, file size in bytes)
    """
    # Adaptive chunk size based on file size for better performance
    if chunk_size is None:
        try:
            file_size = path.stat().st_size
            if file_size > 50 * 1024 * 1024:  # > 50MB
                chunk_size = 8 * 1024 * 1024  # 8MB chunks
            elif file_size > 10 * 1024 * 1024:  # > 10MB
                chunk_size = 4 * 1024 * 1024  # 4MB chunks
            else:
                chunk_size = 1024 * 1024  # 1MB chunks (default)
        except OSError:
            # If we can't stat, use default
            chunk_size = 1024 * 1024
    
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size



