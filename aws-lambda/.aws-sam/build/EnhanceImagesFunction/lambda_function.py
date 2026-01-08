"""
AWS Lambda function for automatic lighting enhancement of uploaded images.

This function is triggered by S3 events when images are uploaded to the
share/ prefix. It downloads the image, applies automatic lighting enhancements,
and uploads the enhanced version to the enhanced/ prefix.
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageOps

from enhancement import enhance_image_auto

# Initialize S3 client (reused for connection pooling)
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
    
    Cost optimizations:
    - Early exit for non-JPEG files (saves compute time)
    - Idempotency check (prevents duplicate processing)
    - Efficient error handling
    
    Returns:
        dict with status and metadata
    """
    start_time = time.time()
    
    # Early exit: Skip non-image files (saves Lambda compute time)
    if not key.lower().endswith((".jpg", ".jpeg")):
        return {
            "status": "skipped",
            "reason": "not_a_jpeg",
            "key": key,
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    
    # Idempotency check: Skip if already enhanced (prevents duplicate processing cost)
    enhanced_key = get_enhanced_key(key)
    try:
        s3_client.head_object(Bucket=bucket, Key=enhanced_key)
        return {
            "status": "skipped",
            "reason": "already_enhanced",
            "key": key,
            "enhanced_key": enhanced_key,
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    except ClientError as e:
        # In some S3 configurations, HEAD on a missing key can return 403 instead of 404.
        # Treat both as "not found" for idempotency purposes; we'll still fail later if
        # the role truly lacks access to the source object or the destination prefix.
        if e.response["Error"]["Code"] not in ("404", "403"):
            raise  # Re-raise if it's not a "not found" / "forbidden" response
    
    # Download image to temporary file
    input_path = None
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_input:
            input_path = Path(tmp_input.name)
            try:
                s3_client.download_file(bucket, key, str(input_path))
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return {
                        "status": "skipped",
                        "reason": "source_not_found",
                        "key": key,
                    }
                raise  # Re-raise other errors
            
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
                    
                    # Clean up output file immediately after upload
                    output_path.unlink()
                    output_path = None
            
            duration_ms = int((time.time() - start_time) * 1000)
            return {
                "status": "success",
                "key": key,
                "enhanced_key": enhanced_key,
                "duration_ms": duration_ms,
            }
            
    finally:
        # Clean up input file
        if input_path and input_path.exists():
            try:
                input_path.unlink()
            except Exception:
                pass  # Ignore cleanup errors
        # Clean up output file if still exists (error case)
        if output_path and output_path.exists():
            try:
                output_path.unlink()
            except Exception:
                pass


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for S3 object-created notifications.
    
    Supported event structures:
    
    1) S3 notification (direct S3 → Lambda):
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
    
    2) EventBridge (S3 → EventBridge → Lambda):
    {
        "source": "aws.s3",
        "detail-type": "Object Created",
        "detail": {
            "bucket": {"name": "bucket-name"},
            "object": {"key": "sessions/.../share/IMG_001.jpg"}
        }
    }
    
    Cost optimizations:
    - Early exit for non-JPEG files
    - Early exit for files not in share/ prefix
    - Idempotency check (skip if already enhanced)
    - Efficient error handling to avoid unnecessary processing
    """
    results = []
    errors = []
    
    def _normalize_records(evt: dict[str, Any]) -> list[dict[str, Any]]:
        """Return a list of pseudo-S3-records in the shape of evt['Records'][]."""
        if isinstance(evt, dict) and isinstance(evt.get("Records"), list):
            return [r for r in evt["Records"] if isinstance(r, dict)]
        # EventBridge S3 Object Created event (single record)
        if (
            isinstance(evt, dict)
            and evt.get("source") == "aws.s3"
            and isinstance(evt.get("detail"), dict)
        ):
            detail = evt["detail"]
            bucket_name = (detail.get("bucket") or {}).get("name")
            object_key = (detail.get("object") or {}).get("key")
            if bucket_name and object_key:
                return [
                    {
                        "s3": {
                            "bucket": {"name": bucket_name},
                            "object": {"key": object_key},
                        }
                    }
                ]
        return []
    
    records = _normalize_records(event)
    
    # Get bucket from environment or from the first record
    bucket = S3_BUCKET
    if not bucket and records:
        bucket = (records[0].get("s3") or {}).get("bucket", {}).get("name", "")
    
    if not bucket:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "S3_BUCKET not configured"}),
        }
    
    # Early exit if no records (unsupported event shape or empty payload)
    if not records:
        return {
            "statusCode": 200,
            "body": json.dumps({
                "processed": 0,
                "success": 0,
                "skipped": 0,
                "errors": 0,
                "results": [],
            }),
        }
    
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

