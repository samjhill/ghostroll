"""
AWS Lambda function for automatic lighting enhancement of uploaded images.

This function is triggered by S3 events when images are uploaded to the
share/ prefix. It downloads the image, applies automatic lighting enhancements,
and uploads the enhanced version to the enhanced/ prefix.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

from enhancement import enhance_image_auto

# Initialize S3 client
s3_client = boto3.client("s3")

# Configuration from environment variables
S3_BUCKET = os.environ.get("S3_BUCKET", "")
ENHANCED_PREFIX = os.environ.get("ENHANCED_PREFIX", "enhanced")
QUALITY = int(os.environ.get("ENHANCEMENT_QUALITY", "92"))  # Slightly higher than share quality


def get_enhanced_key(original_key: str) -> str:
    """
    Convert original S3 key to enhanced key.
    
    Example:
        sessions/shoot-2024-01-01_120000/share/IMG_001.jpg
        -> sessions/shoot-2024-01-01_120000/enhanced/IMG_001.jpg
    """
    # Split the key into parts
    parts = original_key.split("/")
    
    # Find the 'share' part and replace with 'enhanced'
    if "share" in parts:
        share_idx = parts.index("share")
        parts[share_idx] = ENHANCED_PREFIX
        return "/".join(parts)
    
    # Fallback: insert 'enhanced' before filename
    if len(parts) > 0:
        parts.insert(-1, ENHANCED_PREFIX)
        return "/".join(parts)
    
    return original_key


def process_image(bucket: str, key: str) -> dict[str, Any]:
    """
    Download, enhance, and upload an image.
    
    Returns:
        dict with status and metadata
    """
    # Skip non-image files
    if not key.lower().endswith((".jpg", ".jpeg")):
        return {
            "status": "skipped",
            "reason": "not_a_jpeg",
            "key": key,
        }
    
    # Check if enhanced version already exists
    enhanced_key = get_enhanced_key(key)
    try:
        s3_client.head_object(Bucket=bucket, Key=enhanced_key)
        return {
            "status": "skipped",
            "reason": "already_enhanced",
            "key": key,
            "enhanced_key": enhanced_key,
        }
    except ClientError as e:
        if e.response["Error"]["Code"] != "404":
            raise  # Re-raise if it's not a "not found" error
    
    # Download image to temporary file
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_input:
        input_path = Path(tmp_input.name)
        try:
            s3_client.download_file(bucket, key, str(input_path))
            
            # Enhance image
            with Image.open(input_path) as img:
                # Auto-orient based on EXIF
                img = ImageOps.exif_transpose(img)
                
                # Apply enhancements
                enhanced_img = enhance_image_auto(img)
                
                # Save enhanced image to temporary file
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_output:
                    output_path = Path(tmp_output.name)
                    enhanced_img.save(
                        output_path,
                        format="JPEG",
                        quality=QUALITY,
                        optimize=True,
                        progressive=True,
                    )
                    
                    # Upload enhanced image
                    s3_client.upload_file(
                        str(output_path),
                        bucket,
                        enhanced_key,
                        ExtraArgs={
                            "ContentType": "image/jpeg",
                            "Metadata": {
                                "source-key": key,
                                "enhanced": "true",
                            },
                        },
                    )
                    
                    # Clean up
                    output_path.unlink()
            
            return {
                "status": "success",
                "key": key,
                "enhanced_key": enhanced_key,
            }
            
        finally:
            # Clean up input file
            if input_path.exists():
                input_path.unlink()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for S3 event notifications.
    
    Expected event structure (S3 EventBridge):
    {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": "bucket-name"},
                    "object": {"key": "sessions/.../share/IMG_001.jpg"}
                }
            }
        ]
    }
    """
    results = []
    errors = []
    
    # Get bucket from environment or first record
    bucket = S3_BUCKET
    if not bucket:
        # Try to get from event
        if "Records" in event and len(event["Records"]) > 0:
            bucket = event["Records"][0]["s3"]["bucket"]["name"]
    
    if not bucket:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "S3_BUCKET not configured"}),
        }
    
    # Process each S3 event record
    records = event.get("Records", [])
    
    for record in records:
        try:
            # Extract S3 object info
            s3_info = record.get("s3", {})
            key = s3_info.get("object", {}).get("key", "")
            
            # URL decode the key (S3 keys are URL-encoded)
            import urllib.parse
            key = urllib.parse.unquote_plus(key)
            
            # Only process files in share/ prefix
            if "/share/" not in key:
                results.append({
                    "status": "skipped",
                    "reason": "not_in_share_prefix",
                    "key": key,
                })
                continue
            
            # Process the image
            result = process_image(bucket, key)
            results.append(result)
            
        except Exception as e:
            error_info = {
                "status": "error",
                "key": key if "key" in locals() else "unknown",
                "error": str(e),
                "error_type": type(e).__name__,
            }
            errors.append(error_info)
            results.append(error_info)
    
    # Return summary
    success_count = sum(1 for r in results if r.get("status") == "success")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    error_count = len(errors)
    
    return {
        "statusCode": 200 if error_count == 0 else 207,  # 207 = Multi-Status
        "body": json.dumps({
            "processed": len(results),
            "success": success_count,
            "skipped": skipped_count,
            "errors": error_count,
            "results": results,
        }),
    }

