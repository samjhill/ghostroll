#!/usr/bin/env python3
"""Debug script to analyze why images might be missing from a gallery."""

import json
import sys
from pathlib import Path
from typing import Set

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("ERROR: boto3 not installed. Install with: pip install boto3")
    sys.exit(1)


def list_s3_objects(bucket: str, prefix: str) -> Set[str]:
    """List all S3 objects with the given prefix."""
    s3 = boto3.client("s3")
    objects = set()
    paginator = s3.get_paginator("list_objects_v2")
    
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" not in page:
                continue
            for obj in page["Contents"]:
                objects.add(obj["Key"])
    except ClientError as e:
        print(f"ERROR listing S3 objects: {e}")
        return set()
    
    return objects


def main():
    if len(sys.argv) < 2:
        print("Usage: python debug_session.py <session_id> [base_dir] [s3_bucket]")
        print("Example: python debug_session.py shoot-2026-01-08_030203_795425")
        sys.exit(1)
    
    session_id = sys.argv[1]
    base_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "ghostroll"
    s3_bucket = sys.argv[3] if len(sys.argv) > 3 else None
    
    session_dir = base_dir / session_id
    if not session_dir.exists():
        print(f"ERROR: Session directory not found: {session_dir}")
        print(f"Please check the session ID and base directory.")
        sys.exit(1)
    
    print(f"🔍 Debugging session: {session_id}")
    print(f"📁 Session directory: {session_dir}")
    print()
    
    # Check local files
    thumbs_dir = session_dir / "derived" / "thumbs"
    share_dir = session_dir / "derived" / "share"
    originals_dir = session_dir / "originals"
    
    print("📊 Local Files Analysis")
    print("-" * 60)
    
    # Count originals
    if originals_dir.exists():
        original_files = list(originals_dir.rglob("*"))
        original_files = [f for f in original_files if f.is_file() and f.suffix.lower() in [".jpg", ".jpeg", ".cr2", ".cr3", ".nef", ".arw"]]
        print(f"Originals: {len(original_files)} files")
        if original_files:
            print(f"  Sample: {original_files[0].name}")
    else:
        print("Originals: directory not found")
        original_files = []
    
    # Count thumbs
    thumb_files = []
    if thumbs_dir.exists():
        thumb_files = list(thumbs_dir.rglob("*"))
        thumb_files = [f for f in thumb_files if f.is_file()]
        print(f"Thumbs: {len(thumb_files)} files")
        if thumb_files:
            print(f"  Sample: {thumb_files[0].relative_to(thumbs_dir)}")
    else:
        print("Thumbs: directory not found")
    
    # Count share files
    share_files = []
    if share_dir.exists():
        share_files = list(share_dir.rglob("*"))
        share_files = [f for f in share_files if f.is_file()]
        print(f"Share: {len(share_files)} files")
        if share_files:
            print(f"  Sample: {share_files[0].relative_to(share_dir)}")
    else:
        print("Share: directory not found")
    
    print()
    
    # Compare thumb vs share (they should match)
    print("🔍 File Matching Analysis")
    print("-" * 60)
    
    if thumb_files and share_files:
        # Build sets of relative paths
        thumb_rel = {f.relative_to(thumbs_dir).with_suffix(".jpg") for f in thumb_files}
        share_rel = {f.relative_to(share_dir) for f in share_files}
        
        missing_in_share = thumb_rel - share_rel
        missing_in_thumbs = share_rel - thumb_rel
        
        print(f"Thumb files: {len(thumb_rel)}")
        print(f"Share files: {len(share_rel)}")
        print(f"Matching pairs: {len(thumb_rel & share_rel)}")
        
        if missing_in_share:
            print(f"⚠️  Thumbs without share files: {len(missing_in_share)}")
            for rel in sorted(missing_in_share)[:5]:
                print(f"  - {rel}")
            if len(missing_in_share) > 5:
                print(f"  ... and {len(missing_in_share) - 5} more")
        
        if missing_in_thumbs:
            print(f"⚠️  Share files without thumbs: {len(missing_in_thumbs)}")
            for rel in sorted(missing_in_thumbs)[:5]:
                print(f"  - {rel}")
            if len(missing_in_thumbs) > 5:
                print(f"  ... and {len(missing_in_thumbs) - 5} more")
    
    print()
    
    # Check gallery HTML
    print("📄 Gallery HTML Analysis")
    print("-" * 60)
    
    index_html = session_dir / "index.html"
    if index_html.exists():
        content = index_html.read_text(encoding="utf-8")
        # Count image tiles in HTML
        tile_count = content.count('class="tile"')
        print(f"Gallery HTML: Found {tile_count} image tiles")
        
        # Extract image sources
        import re
        img_srcs = re.findall(r'<img src="([^"]+)"', content)
        thumb_srcs = [s for s in img_srcs if "/thumbs/" in s or "thumbs" in s]
        print(f"Thumb images in HTML: {len(thumb_srcs)}")
        
        if thumb_srcs and thumb_files:
            # Check if all thumb files are in HTML
            html_thumb_rel = set()
            for src in thumb_srcs:
                # Extract relative path from src
                if "derived/thumbs/" in src:
                    rel = src.split("derived/thumbs/", 1)[1]
                    html_thumb_rel.add(rel)
            
            local_thumb_rel = {str(f.relative_to(thumbs_dir)) for f in thumb_files}
            missing_in_html = local_thumb_rel - html_thumb_rel
            
            if missing_in_html:
                print(f"⚠️  Thumb files NOT in HTML: {len(missing_in_html)}")
                for rel in sorted(missing_in_html)[:5]:
                    print(f"  - {rel}")
                if len(missing_in_html) > 5:
                    print(f"  ... and {len(missing_in_html) - 5} more")
    else:
        print("Gallery HTML: not found")
    
    print()
    
    # Check S3 if bucket provided
    if s3_bucket:
        print("☁️  S3 Upload Analysis")
        print("-" * 60)
        
        prefix = f"{session_id}/"
        s3_objects = list_s3_objects(s3_bucket, prefix)
        
        print(f"S3 objects with prefix '{prefix}': {len(s3_objects)}")
        
        if s3_objects:
            thumbs_in_s3 = {k for k in s3_objects if "/thumbs/" in k}
            share_in_s3 = {k for k in s3_objects if "/share/" in k and not k.endswith("share.zip")}
            index_in_s3 = {k for k in s3_objects if k.endswith("index.html")}
            
            print(f"  Thumbs in S3: {len(thumbs_in_s3)}")
            print(f"  Share files in S3: {len(share_in_s3)}")
            print(f"  Gallery HTML in S3: {'Yes' if index_in_s3 else 'No'}")
            
            if thumb_files and thumbs_in_s3:
                # Compare local thumbs to S3
                expected_thumbs = {f"{session_id}/thumbs/{f.relative_to(thumbs_dir).as_posix()}" for f in thumb_files}
                missing_in_s3 = expected_thumbs - thumbs_in_s3
                
                if missing_in_s3:
                    print(f"⚠️  Thumb files NOT uploaded to S3: {len(missing_in_s3)}")
                    for key in sorted(missing_in_s3)[:5]:
                        print(f"  - {key}")
                    if len(missing_in_s3) > 5:
                        print(f"  ... and {len(missing_in_s3) - 5} more")
            
            if share_files and share_in_s3:
                # Compare local share to S3
                expected_share = {f"{session_id}/share/{f.relative_to(share_dir).as_posix()}" for f in share_files}
                missing_in_s3 = expected_share - share_in_s3
                
                if missing_in_s3:
                    print(f"⚠️  Share files NOT uploaded to S3: {len(missing_in_s3)}")
                    for key in sorted(missing_in_s3)[:5]:
                        print(f"  - {key}")
                    if len(missing_in_s3) > 5:
                        print(f"  ... and {len(missing_in_s3) - 5} more")
        else:
            print("⚠️  No objects found in S3 (session may not have been uploaded)")
    else:
        print("☁️  S3 Analysis: skipped (provide bucket name to check uploads)")
    
    print()
    
    # Check logs
    print("📋 Log Analysis")
    print("-" * 60)
    
    log_file = session_dir / "ghostroll.log"
    if log_file.exists():
        log_lines = log_file.read_text(encoding="utf-8").splitlines()
        print(f"Log file: {len(log_lines)} lines")
        
        # Look for errors/warnings
        errors = [l for l in log_lines if "ERROR" in l or "error" in l.lower()]
        warnings = [l for l in log_lines if "WARNING" in l or "warning" in l.lower() and "ERROR" not in l]
        
        print(f"Errors in log: {len(errors)}")
        if errors:
            for err in errors[-5:]:  # Last 5 errors
                print(f"  - {err[:100]}")
        
        print(f"Warnings in log: {len(warnings)}")
        if warnings:
            for warn in warnings[-5:]:  # Last 5 warnings
                print(f"  - {warn[:100]}")
        
        # Look for upload failures
        upload_failures = [l for l in log_lines if "Failed to upload" in l or "upload failed" in l.lower()]
        if upload_failures:
            print(f"Upload failures: {len(upload_failures)}")
            for fail in upload_failures[-5:]:
                print(f"  - {fail[:100]}")
        
        # Look for processing failures
        proc_failures = [l for l in log_lines if "Failed to process" in l or "process failed" in l.lower()]
        if proc_failures:
            print(f"Processing failures: {len(proc_failures)}")
            for fail in proc_failures[-5:]:
                print(f"  - {fail[:100]}")
    else:
        print("Log file: not found")
    
    print()
    print("✅ Analysis complete!")


if __name__ == "__main__":
    main()

