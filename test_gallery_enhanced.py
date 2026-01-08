#!/usr/bin/env python3
"""
Test script to regenerate a gallery with enhanced image support.
This demonstrates that the gallery can detect and use enhanced images.
"""

import sys
from pathlib import Path

from ghostroll.aws_boto3 import s3_object_exists, s3_presign_url
from ghostroll.config import load_config
from ghostroll.gallery import build_index_html_presigned

def regenerate_gallery_with_enhanced(session_id: str):
    """Regenerate gallery HTML with enhanced image support."""
    cfg = load_config()
    prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
    
    # List all thumbnails in S3
    import boto3
    s3 = boto3.client('s3')
    
    thumb_prefix = f"{prefix}/thumbs/"
    response = s3.list_objects_v2(Bucket=cfg.s3_bucket, Prefix=thumb_prefix)
    
    if "Contents" not in response:
        print(f"No thumbnails found for session {session_id}")
        return
    
    items = []
    for obj in response["Contents"]:
        thumb_key = obj["Key"]
        # Extract relative path: sessions/.../thumbs/path/to/img.jpg -> path/to/img.jpg
        rel_path = thumb_key.replace(thumb_prefix, "")
        
        # Build keys
        share_key = f"{prefix}/share/{rel_path}"
        enhanced_key = f"{prefix}/enhanced/{rel_path}"
        
        # Presign URLs
        thumb_url = s3_presign_url(
            bucket=cfg.s3_bucket,
            key=thumb_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        share_url = s3_presign_url(
            bucket=cfg.s3_bucket,
            key=share_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
        
        # Check for enhanced version
        enhanced_url = None
        if s3_object_exists(bucket=cfg.s3_bucket, key=enhanced_key):
            enhanced_url = s3_presign_url(
                bucket=cfg.s3_bucket,
                key=enhanced_key,
                expires_in_seconds=cfg.presign_expiry_seconds,
            )
            print(f"✓ Enhanced version available: {rel_path}")
        else:
            print(f"  No enhanced version: {rel_path}")
        
        items.append((thumb_url, share_url, rel_path, "", enhanced_url))
    
    # Build gallery
    session_dir = cfg.sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    out_path = session_dir / "index.enhanced.html"
    
    build_index_html_presigned(
        session_id=session_id,
        items=items,
        download_href=None,  # Could add download zip URL
        out_path=out_path,
    )
    
    print(f"\n✓ Gallery generated: {out_path}")
    print(f"  Total images: {len(items)}")
    print(f"  Enhanced images: {sum(1 for item in items if item[4])}")
    
    # Also upload to S3
    index_key = f"{prefix}/index.html"
    s3.upload_file(
        str(out_path),
        cfg.s3_bucket,
        index_key,
        ExtraArgs={"ContentType": "text/html"},
    )
    print(f"✓ Uploaded to S3: s3://{cfg.s3_bucket}/{index_key}")
    
    # Generate presigned URL
    gallery_url = s3_presign_url(
        bucket=cfg.s3_bucket,
        key=index_key,
        expires_in_seconds=cfg.presign_expiry_seconds,
    )
    print(f"\n🔗 Gallery URL: {gallery_url}")

if __name__ == "__main__":
    session_id = sys.argv[1] if len(sys.argv) > 1 else "shoot-2026-01-01_164554_033504"
    print(f"Regenerating gallery for session: {session_id}\n")
    regenerate_gallery_with_enhanced(session_id)


