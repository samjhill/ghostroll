"""
Rebuild and upload S3-hosted gallery ``index.html`` for a session (e.g. after HTML template changes).

Lists ``{prefix}/thumbs/**/*.jpg`` in the bucket, presigns thumb/share/enhanced/tags URLs like the
main pipeline, embeds a fresh presigned URL for the gallery page in the share strip, and uploads
``index.html`` over the existing object.
"""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3

from .aws_boto3 import s3_object_exists, s3_presign_url, s3_upload_file
from .config import Config
from .gallery import build_index_html_presigned


def _thumb_keys_for_session(*, bucket: str, prefix: str) -> list[str]:
    """S3 keys under ``{prefix}/thumbs/`` ending in .jpg / .jpeg."""
    client = boto3.client("s3")
    thumb_prefix = f"{prefix}/thumbs/"
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=thumb_prefix):
        for obj in page.get("Contents") or []:
            k = obj.get("Key")
            if not k or not isinstance(k, str):
                continue
            lk = k.lower()
            if lk.endswith(".jpg") or lk.endswith(".jpeg"):
                keys.append(k)
    keys.sort()
    return keys


def _presign_row(
    cfg: Config,
    prefix: str,
    thumb_key: str,
) -> tuple[str, str, str, str, float, str | None, str | None]:
    thumb_prefix = f"{prefix}/thumbs/"
    if not thumb_key.startswith(thumb_prefix):
        raise ValueError(f"unexpected thumb key: {thumb_key}")
    rel_posix = thumb_key[len(thumb_prefix) :]
    share_key = f"{prefix}/share/{Path(rel_posix).with_suffix('.jpg').as_posix()}"
    enhanced_key = f"{prefix}/enhanced/{Path(rel_posix).with_suffix('.jpg').as_posix()}"
    tags_key = f"{prefix}/tags/{Path(rel_posix).with_suffix('.json').as_posix()}"

    enhanced_url = None
    if s3_object_exists(bucket=cfg.s3_bucket, key=enhanced_key):
        enhanced_url = s3_presign_url(
            bucket=cfg.s3_bucket,
            key=enhanced_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
    tags_url = None
    if s3_object_exists(bucket=cfg.s3_bucket, key=tags_key):
        tags_url = s3_presign_url(
            bucket=cfg.s3_bucket,
            key=tags_key,
            expires_in_seconds=cfg.presign_expiry_seconds,
        )
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
    title = rel_posix
    return (thumb_url, share_url, title, "", 9e18, enhanced_url, tags_url)


def republish_session_gallery_s3(*, cfg: Config, session_id: str) -> str:
    """
    Rebuild ``index.html`` for ``session_id`` and upload to the configured bucket.

    Returns a fresh presigned URL for the gallery ``index.html`` (same shape as ``share.txt``).
    """
    prefix = f"{cfg.s3_prefix_root}{session_id}".rstrip("/")
    s3_index_key = f"{prefix}/index.html"
    bucket = cfg.s3_bucket

    thumb_keys = _thumb_keys_for_session(bucket=bucket, prefix=prefix)
    if not thumb_keys:
        raise ValueError(f"No JPEG thumbs found under s3://{bucket}/{prefix}/thumbs/")

    presigned_items: list[tuple[str, str, str, str, float, str | None, str | None]] = []
    workers = max(1, min(cfg.presign_workers, 16))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_presign_row, cfg, prefix, k): k for k in thumb_keys}
        for fut in as_completed(futs):
            presigned_items.append(fut.result())

    presigned_items.sort(key=lambda x: (x[4], x[2]))
    presigned_ui = [(a, b, c, d, e, f) for (a, b, c, d, _ts, e, f) in presigned_items]

    download_zip_url = s3_presign_url(
        bucket=bucket,
        key=f"{prefix}/share.zip",
        expires_in_seconds=cfg.presign_expiry_seconds,
    )
    gallery_page_url = s3_presign_url(
        bucket=bucket,
        key=s3_index_key,
        expires_in_seconds=cfg.presign_expiry_seconds,
    )

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "index.s3.html"
        build_index_html_presigned(
            session_id=session_id,
            items=presigned_ui,
            download_href=download_zip_url,
            out_path=out,
            share_page_url=gallery_page_url,
        )
        s3_upload_file(
            out,
            bucket=bucket,
            key=s3_index_key,
            content_type="text/html; charset=utf-8",
        )

    return gallery_page_url
