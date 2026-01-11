from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_boto3_client_caches():
    """
    Tests monkeypatch boto3 clients, but ghostroll caches global S3 clients for pooling.
    Reset between tests so mocks are respected and tests don't bleed across each other.
    """
    try:
        import ghostroll.aws_boto3 as aws_boto3

        aws_boto3._s3_client = None  # type: ignore[attr-defined]
        aws_boto3._presign_client = None  # type: ignore[attr-defined]
    except Exception:
        pass
    yield
    try:
        import ghostroll.aws_boto3 as aws_boto3

        aws_boto3._s3_client = None  # type: ignore[attr-defined]
        aws_boto3._presign_client = None  # type: ignore[attr-defined]
    except Exception:
        pass

