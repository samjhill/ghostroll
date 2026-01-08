#!/usr/bin/env python3
"""
Comprehensive test for gallery toggle functionality.
Tests that enhanced images are detected and toggle works correctly.
"""

import json
import sys
from pathlib import Path

from ghostroll.aws_boto3 import s3_object_exists, s3_presign_url
from ghostroll.config import load_config
from ghostroll.gallery import build_index_html_presigned

def test_gallery_with_enhanced(session_id: str):
    """Test gallery generation with enhanced images."""
    print(f"\n=== Testing Gallery for Session: {session_id} ===\n")
    
    cfg = load_config()
    prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
    
    import boto3
    s3 = boto3.client('s3')
    
    # List all thumbnails
    thumb_prefix = f"{prefix}/thumbs/"
    response = s3.list_objects_v2(Bucket=cfg.s3_bucket, Prefix=thumb_prefix)
    
    if "Contents" not in response:
        print(f"❌ No thumbnails found for session {session_id}")
        return False
    
    items = []
    enhanced_count = 0
    total_count = 0
    
    for obj in response["Contents"]:
        thumb_key = obj["Key"]
        rel_path = thumb_key.replace(thumb_prefix, "")
        total_count += 1
        
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
            enhanced_count += 1
            print(f"  ✅ Enhanced: {rel_path}")
        else:
            print(f"  ⚠️  No enhanced: {rel_path}")
        
        items.append((thumb_url, share_url, rel_path, "", enhanced_url))
    
    print(f"\n  Total images: {total_count}")
    print(f"  Enhanced images: {enhanced_count}")
    
    # Build gallery
    session_dir = cfg.sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    out_path = session_dir / "index.test.html"
    
    build_index_html_presigned(
        session_id=session_id,
        items=items,
        download_href=None,
        out_path=out_path,
    )
    
    # Verify gallery HTML
    with open(out_path, 'r') as f:
        html_content = f.read()
    
    has_toggle = 'enhanceToggle' in html_content
    has_enhanced_data = 'data-enhanced' in html_content
    has_toggle_js = 'updateEnhanceToggle' in html_content
    has_localstorage = 'localStorage.getItem' in html_content
    
    print(f"\n=== Gallery HTML Verification ===")
    print(f"  Toggle button: {'✅' if has_toggle else '❌'}")
    print(f"  Enhanced data attributes: {'✅' if has_enhanced_data else '❌'}")
    print(f"  Toggle JavaScript: {'✅' if has_toggle_js else '❌'}")
    print(f"  localStorage support: {'✅' if has_localstorage else '❌'}")
    
    # Count enhanced data attributes
    enhanced_attr_count = html_content.count('data-enhanced=')
    print(f"  Enhanced attributes in HTML: {enhanced_attr_count}")
    
    if enhanced_count > 0:
        assert has_toggle, "Toggle button should be present when enhanced images exist"
        assert has_enhanced_data, "Enhanced data should be present"
        assert enhanced_attr_count == enhanced_count, f"Should have {enhanced_count} enhanced attributes, found {enhanced_attr_count}"
    
    print(f"\n✅ Gallery test passed!")
    print(f"   Gallery saved to: {out_path}")
    
    return True

if __name__ == "__main__":
    session_id = sys.argv[1] if len(sys.argv) > 1 else "shoot-2026-01-01_164554_033504"
    success = test_gallery_with_enhanced(session_id)
    sys.exit(0 if success else 1)


