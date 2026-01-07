#!/usr/bin/env python3
"""
Test script to run enhancement locally against existing S3 images.
This allows testing the enhancement workflow without deploying Lambda.
"""

import os
import sys
import tempfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

from enhancement import enhance_image_auto

# Configuration
S3_BUCKET = os.environ.get("S3_BUCKET", "photo-ingest-project")
SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else "shoot-2026-01-01_164554_033504"

s3_client = boto3.client("s3")


def get_enhanced_key(original_key: str) -> str:
    """Convert share key to enhanced key."""
    return original_key.replace("/share/", "/enhanced/")


def process_image(key: str) -> dict:
    """Download, enhance, and upload an image."""
    print(f"Processing: {key}")
    
    # Check if enhanced already exists
    enhanced_key = get_enhanced_key(key)
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=enhanced_key)
        print(f"  ✓ Already enhanced: {enhanced_key}")
        return {"status": "skipped", "reason": "already_exists"}
    except ClientError as e:
        if e.response["Error"]["Code"] != "404":
            raise
    
    # Download
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_input:
        input_path = Path(tmp_input.name)
        try:
            print(f"  Downloading from S3...")
            s3_client.download_file(S3_BUCKET, key, str(input_path))
            
            # Enhance
            print(f"  Enhancing image...")
            with Image.open(input_path) as img:
                img = ImageOps.exif_transpose(img)
                enhanced_img = enhance_image_auto(img)
                
                # Save
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_output:
                    output_path = Path(tmp_output.name)
                    enhanced_img.save(
                        output_path,
                        format="JPEG",
                        quality=92,
                        optimize=True,
                        progressive=True,
                    )
                    
                    # Upload
                    print(f"  Uploading enhanced version to {enhanced_key}...")
                    s3_client.upload_file(
                        str(output_path),
                        S3_BUCKET,
                        enhanced_key,
                        ExtraArgs={
                            "ContentType": "image/jpeg",
                            "Metadata": {
                                "source-key": key,
                                "enhanced": "true",
                            },
                        },
                    )
                    
                    output_path.unlink()
            
            print(f"  ✓ Successfully enhanced: {enhanced_key}")
            return {"status": "success", "enhanced_key": enhanced_key}
            
        finally:
            if input_path.exists():
                input_path.unlink()


def main():
    """Process all share images in a session."""
    print(f"Processing session: {SESSION_ID}")
    print(f"Bucket: {S3_BUCKET}")
    print()
    
    # List all share images in the session
    prefix = f"sessions/{SESSION_ID}/share/"
    print(f"Listing images in: {prefix}")
    
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=prefix,
        )
        
        if "Contents" not in response:
            print(f"No images found in {prefix}")
            return
        
        images = [obj["Key"] for obj in response["Contents"] if obj["Key"].lower().endswith((".jpg", ".jpeg"))]
        
        if not images:
            print(f"No JPEG images found in {prefix}")
            return
        
        print(f"Found {len(images)} images to process\n")
        
        # Process each image
        results = []
        for i, key in enumerate(images, 1):
            print(f"[{i}/{len(images)}] {key.split('/')[-1]}")
            try:
                result = process_image(key)
                results.append(result)
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results.append({"status": "error", "key": key, "error": str(e)})
            print()
        
        # Summary
        success = sum(1 for r in results if r.get("status") == "success")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        errors = sum(1 for r in results if r.get("status") == "error")
        
        print("=" * 60)
        print(f"Summary:")
        print(f"  Total: {len(results)}")
        print(f"  Success: {success}")
        print(f"  Skipped: {skipped}")
        print(f"  Errors: {errors}")
        print("=" * 60)
        
    except ClientError as e:
        print(f"Error accessing S3: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

