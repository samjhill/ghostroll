"""
AWS Lambda function for automatic object/scene tagging of uploaded images.

Triggered by S3 events on new objects. It filters to JPEGs under the `share/`
prefix, calls AWS Rekognition DetectLabels, and writes results to a JSON sidecar
under the `tags/` prefix.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

# Reused clients for connection pooling
s3_client = boto3.client("s3")
rekognition_client = boto3.client("rekognition")

# Configuration (environment variables)
S3_BUCKET = os.environ.get("S3_BUCKET", "")
TAGS_PREFIX = os.environ.get("TAGS_PREFIX", "tags")
TAG_MIN_CONFIDENCE = float(os.environ.get("TAG_MIN_CONFIDENCE", "70"))
TAG_MAX_LABELS = int(os.environ.get("TAG_MAX_LABELS", "15"))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_tags_key(original_key: str) -> str:
    """
    Convert original S3 key to tag JSON key.

    Example:
        sessions/shoot-2024-01-01_120000/share/IMG_001.jpg
        -> sessions/shoot-2024-01-01_120000/tags/IMG_001.json
    """
    parts = original_key.split("/")

    # Replace share segment with tags prefix
    if "share" in parts:
        share_idx = parts.index("share")
        parts[share_idx] = TAGS_PREFIX

    key = "/".join(parts)

    # Swap extension to .json
    lower = key.lower()
    if lower.endswith(".jpeg"):
        return key[: -len(".jpeg")] + ".json"
    if lower.endswith(".jpg"):
        return key[: -len(".jpg")] + ".json"
    return key + ".json"


def _head_exists(bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        # Some buckets return 403 for missing keys; treat as "not found" for idempotency
        if e.response["Error"]["Code"] in ("404", "403"):
            return False
        raise


def _detect_labels(*, bucket: str, key: str) -> dict[str, Any]:
    resp = rekognition_client.detect_labels(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        MaxLabels=max(1, min(50, TAG_MAX_LABELS)),
        MinConfidence=max(0.0, min(100.0, TAG_MIN_CONFIDENCE)),
    )

    labels_out: list[dict[str, Any]] = []
    for lbl in resp.get("Labels", []) or []:
        if not isinstance(lbl, dict):
            continue
        name = lbl.get("Name")
        conf = lbl.get("Confidence")
        parents = []
        for p in (lbl.get("Parents") or []):
            if isinstance(p, dict) and p.get("Name"):
                parents.append(str(p["Name"]))
        if name and conf is not None:
            labels_out.append(
                {
                    "name": str(name),
                    "confidence": float(conf),
                    "parents": parents,
                }
            )

    labels_out.sort(key=lambda x: (-float(x.get("confidence", 0.0)), str(x.get("name", ""))))

    return {
        "model": "aws-rekognition-detect-labels",
        "source_bucket": bucket,
        "source_key": key,
        "generated_utc": _utc_now_iso(),
        "min_confidence": TAG_MIN_CONFIDENCE,
        "max_labels": TAG_MAX_LABELS,
        "labels": labels_out,
    }


def process_image(bucket: str, key: str) -> dict[str, Any]:
    start_time = time.time()

    lower = key.lower()
    if not (lower.endswith(".jpg") or lower.endswith(".jpeg")):
        return {
            "status": "skipped",
            "reason": "not_a_jpeg",
            "key": key,
            "duration_ms": int((time.time() - start_time) * 1000),
        }
    if "/share/" not in key:
        return {
            "status": "skipped",
            "reason": "not_in_share_prefix",
            "key": key,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    tags_key = get_tags_key(key)

    if _head_exists(bucket, tags_key):
        return {
            "status": "skipped",
            "reason": "already_tagged",
            "key": key,
            "tags_key": tags_key,
            "duration_ms": int((time.time() - start_time) * 1000),
        }

    try:
        tags = _detect_labels(bucket=bucket, key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("InvalidS3ObjectException", "NoSuchKey", "404"):
            return {
                "status": "skipped",
                "reason": "source_not_found",
                "key": key,
                "duration_ms": int((time.time() - start_time) * 1000),
            }
        raise

    body = (json.dumps(tags, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    s3_client.put_object(
        Bucket=bucket,
        Key=tags_key,
        Body=body,
        ContentType="application/json; charset=utf-8",
        Metadata={"source-key": key, "ghostroll-tags": "true"},
    )

    return {
        "status": "success",
        "key": key,
        "tags_key": tags_key,
        "duration_ms": int((time.time() - start_time) * 1000),
        "label_count": len(tags.get("labels") or []),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    def _normalize_records(evt: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(evt, dict) and isinstance(evt.get("Records"), list):
            return [r for r in evt["Records"] if isinstance(r, dict)]
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

    bucket = S3_BUCKET
    if not bucket and records:
        bucket = (records[0].get("s3") or {}).get("bucket", {}).get("name", "")
    if not bucket:
        return {"statusCode": 400, "body": json.dumps({"error": "S3_BUCKET not configured"})}

    if not records:
        return {
            "statusCode": 200,
            "body": json.dumps(
                {"processed": 0, "success": 0, "skipped": 0, "errors": 0, "results": []}
            ),
        }

    import urllib.parse

    for record in records:
        key = "unknown"
        try:
            s3_info = record.get("s3", {})
            key = (s3_info.get("object") or {}).get("key", "") or ""
            key = urllib.parse.unquote_plus(key)
            results.append(process_image(bucket, key))
        except Exception as e:
            error_info = {
                "status": "error",
                "key": key,
                "error": str(e),
                "error_type": type(e).__name__,
            }
            errors.append(error_info)
            results.append(error_info)

    success_count = sum(1 for r in results if r.get("status") == "success")
    skipped_count = sum(1 for r in results if r.get("status") == "skipped")
    error_count = len(errors)

    return {
        "statusCode": 200 if error_count == 0 else 207,
        "body": json.dumps(
            {
                "processed": len(results),
                "success": success_count,
                "skipped": skipped_count,
                "errors": error_count,
                "results": results,
            }
        ),
    }

