#!/usr/bin/env python3
"""
Generate realistic test RAW images for GhostRoll ingest testing.

Creates unique, realistically-sized RAW files (20-50MB each) and places them
in the DCIM folder structure on the SD card.
"""

import argparse
import random
import sys
from pathlib import Path


# Supported RAW formats from ghostroll/media.py
RAW_EXTS = [".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".rw2"]


def generate_fake_raw(
    output_path: Path,
    target_size_mb: float,
    seed: int | None = None,
) -> int:
    """
    Generate a fake RAW file with random binary data.
    
    Args:
        output_path: Where to save the RAW file
        target_size_mb: Target file size in MB
        seed: Random seed for reproducibility (uses random if None)
    
    Returns:
        Size of the generated file in bytes
    """
    if seed is not None:
        random.seed(seed)
    
    target_size_bytes = int(target_size_mb * 1024 * 1024)
    
    # Generate random binary data to simulate RAW file content
    # Use a pattern that includes some structure to make it more realistic
    chunk_size = 1024 * 1024  # 1MB chunks
    chunks = []
    
    for i in range(0, target_size_bytes, chunk_size):
        remaining = min(chunk_size, target_size_bytes - i)
        # Create some structured data mixed with random bytes
        # This simulates the structure of real RAW files
        chunk = bytearray()
        for j in range(remaining):
            if j % 100 == 0:
                # Add some structured bytes (like headers/metadata)
                chunk.append(random.randint(0, 255))
            else:
                chunk.append(random.randint(0, 255))
        chunks.append(bytes(chunk))
    
    # Write all chunks to file
    with open(output_path, 'wb') as f:
        for chunk in chunks:
            f.write(chunk)
    
    return output_path.stat().st_size


def find_sd_card() -> Path | None:
    """Find the SD card mounted at /Volumes/auto-import or similar."""
    base_volumes = Path("/Volumes")
    
    # Check for exact match first
    exact_match = base_volumes / "auto-import"
    if exact_match.exists() and exact_match.is_dir():
        return exact_match
    
    # Check for prefix matches
    for vol in base_volumes.iterdir():
        if vol.name.startswith("auto-import"):
            return vol
    
    return None


def get_dcim_folder(sd_root: Path) -> Path:
    """Get or create the DCIM folder structure."""
    dcim = sd_root / "DCIM"
    
    if not dcim.exists():
        dcim.mkdir(parents=True, exist_ok=True)
    
    # Check for existing camera folders (like 100MSDCF, 100CANON, etc.)
    existing_folders = [d for d in dcim.iterdir() if d.is_dir() and d.name.isdigit()]
    
    if existing_folders:
        # Use the first existing folder
        return existing_folders[0]
    else:
        # Create a typical camera folder (100MSDCF is Sony, 100CANON is Canon)
        camera_folder = dcim / "100MSDCF"
        camera_folder.mkdir(parents=True, exist_ok=True)
        return camera_folder


def generate_filename(index: int, raw_ext: str, existing_files: set[str]) -> str:
    """Generate a unique camera-style filename with RAW extension."""
    # Try common camera naming patterns
    base_name = f"DSC_{index:05d}"
    patterns = [
        f"{base_name}{raw_ext.upper()}",
        f"{base_name}{raw_ext.lower()}",
        f"IMG_{index:04d}{raw_ext.upper()}",
        f"IMG_{index:04d}{raw_ext.lower()}",
    ]
    
    for pattern in patterns:
        if pattern not in existing_files:
            return pattern
    
    # Fallback to timestamp-based name
    import time
    timestamp = int(time.time() * 1000) % 1000000
    return f"IMG_{timestamp}_{index:04d}{raw_ext.upper()}"


def main():
    parser = argparse.ArgumentParser(
        description="Generate test RAW images for GhostRoll ingest testing"
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=10,
        help="Number of RAW files to generate (default: 10)"
    )
    parser.add_argument(
        "--sd-path",
        type=str,
        help="Path to SD card (default: auto-detect /Volumes/auto-import)"
    )
    parser.add_argument(
        "--min-size-mb",
        type=float,
        default=20.0,
        help="Minimum file size in MB (default: 20.0)"
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        default=50.0,
        help="Maximum file size in MB (default: 50.0)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=RAW_EXTS,
        default=None,
        help="RAW format to use (default: random from supported formats)"
    )
    
    args = parser.parse_args()
    
    # Find SD card
    if args.sd_path:
        sd_root = Path(args.sd_path)
        if not sd_root.exists():
            print(f"Error: SD card path does not exist: {sd_root}", file=sys.stderr)
            sys.exit(1)
    else:
        sd_root = find_sd_card()
        if sd_root is None:
            print("Error: Could not find SD card at /Volumes/auto-import", file=sys.stderr)
            print("Please specify --sd-path or ensure the card is mounted", file=sys.stderr)
            sys.exit(1)
    
    print(f"Found SD card at: {sd_root}")
    
    # Get DCIM folder
    dcim_folder = get_dcim_folder(sd_root)
    print(f"Using DCIM folder: {dcim_folder}")
    
    # Get existing files to avoid duplicates
    existing_files = {f.name for f in dcim_folder.iterdir() if f.is_file()}
    print(f"Found {len(existing_files)} existing files in DCIM folder")
    
    # Generate RAW files
    print(f"\nGenerating {args.count} test RAW files...")
    
    generated = []
    for i in range(args.count):
        # Choose RAW format
        if args.format:
            raw_ext = args.format
        else:
            raw_ext = random.choice(RAW_EXTS)
        
        filename = generate_filename(i + 1, raw_ext, existing_files)
        output_path = dcim_folder / filename
        
        # Vary file size
        target_size_mb = random.uniform(args.min_size_mb, args.max_size_mb)
        
        # Generate the RAW file
        file_size_bytes = generate_fake_raw(
            output_path,
            target_size_mb=target_size_mb,
            seed=random.randint(0, 1000000)
        )
        
        file_size_mb = file_size_bytes / (1024 * 1024)
        generated.append((filename, file_size_mb))
        existing_files.add(filename)
        
        print(f"  [{i+1}/{args.count}] {filename} - {file_size_mb:.2f} MB")
    
    print(f"\n✅ Successfully generated {len(generated)} RAW files")
    print(f"   Total size: {sum(size for _, size in generated):.2f} MB")
    print(f"   Location: {dcim_folder}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

