from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3
    from botocore.client import BaseClient
    from botocore.exceptions import ClientError

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
    from boto3.s3.transfer import TransferConfig
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False
    boto3 = None  # type: ignore[assignment]
    Config = None  # type: ignore[assignment, misc]
    ClientError = Exception  # type: ignore[assignment, misc]
    TransferConfig = None  # type: ignore[assignment, misc]


class AwsBoto3Error(RuntimeError):
    pass


# Global client instances (reused for connection pooling)
_s3_client: BaseClient | None = None
_presign_client: BaseClient | None = None


def _get_s3_client() -> BaseClient:
    """Get or create a reusable S3 client with connection pooling."""
    global _s3_client
    if _s3_client is None:
        if not BOTO3_AVAILABLE:
            raise AwsBoto3Error(
                "boto3 is not installed.\n"
                "  Install with: pip install boto3\n"
                "  Or: pip install -e ."
            )
        
        # Configure for better performance: connection pooling and retries
        config = Config(
            max_pool_connections=50,  # Connection pooling
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'  # Adaptive retry mode
            }
        )
        _s3_client = boto3.client('s3', config=config)
    return _s3_client


def _get_presign_client() -> BaseClient:
    """Get or create a reusable S3 client for presigning (lighter config)."""
    global _presign_client
    if _presign_client is None:
        if not BOTO3_AVAILABLE:
            raise AwsBoto3Error(
                "boto3 is not installed.\n"
                "  Install with: pip install boto3\n"
                "  Or: pip install -e ."
            )
        _presign_client = boto3.client('s3')
    return _presign_client


def _parse_boto3_error(error: ClientError) -> str:
    """Parse boto3 ClientError and return actionable guidance."""
    error_code = error.response.get('Error', {}).get('Code', '')
    error_message = error.response.get('Error', {}).get('Message', str(error))
    error_message_lower = error_message.lower()
    
    if error_code == 'NoCredentialsError' or 'credentials' in error_message_lower:
        return (
            "AWS credentials not configured.\n"
            "  Run: aws configure\n"
            "  Or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables."
        )
    if error_code == 'AccessDenied' or 'access denied' in error_message_lower or 'forbidden' in error_message_lower:
        return (
            "Access denied. Check your AWS IAM permissions:\n"
            "  - s3:PutObject for uploading files\n"
            "  - s3:GetObject for presigning URLs\n"
            "  Verify with: aws sts get-caller-identity"
        )
    if error_code == 'NoSuchBucket' or 'does not exist' in error_message_lower:
        return (
            "S3 bucket does not exist or is not accessible.\n"
            "  Verify the bucket name and your access permissions.\n"
            "  Check with: aws s3 ls s3://<bucket-name>"
        )
    if 'network' in error_message_lower or 'timeout' in error_message_lower or 'connection' in error_message_lower:
        return (
            "Network error connecting to AWS.\n"
            "  Check your internet connection and AWS service status."
        )
    
    return f"Error code: {error_code}"


def s3_upload_file(local_path: Path, *, bucket: str, key: str, retries: int = 3) -> None:
    """Upload a file to S3 using boto3 (faster than AWS CLI subprocess).
    
    Args:
        local_path: Local file path to upload
        bucket: S3 bucket name
        key: S3 object key (path)
        retries: Number of retry attempts (handled by boto3 config)
    
    Raises:
        AwsBoto3Error: If upload fails
    """
    client = _get_s3_client()
    file_size = local_path.stat().st_size
    
    # Use multipart upload for large files (>100MB) for better performance and error recovery
    transfer_config = None
    if file_size > 100 * 1024 * 1024:  # > 100MB
        transfer_config = TransferConfig(
            multipart_threshold=100 * 1024 * 1024,
            max_concurrency=10,
            multipart_chunksize=10 * 1024 * 1024,  # 10MB chunks
        )
    
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if transfer_config:
                client.upload_file(
                    str(local_path),
                    bucket,
                    key,
                    Config=transfer_config
                )
            else:
                client.upload_file(
                    str(local_path),
                    bucket,
                    key
                )
            return  # Success
        except ClientError as e:
            last_error = e
            if attempt < retries:
                # Exponential backoff
                time.sleep(1.5 * attempt)
            else:
                # Final attempt failed
                guidance = _parse_boto3_error(e)
                error_msg = f"Failed to upload {local_path.name} to s3://{bucket}/{key}"
                if guidance:
                    error_msg += f"\n\n{guidance}\n"
                error_msg += f"\nError: {e}"
                raise AwsBoto3Error(error_msg) from e
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(1.5 * attempt)
            else:
                raise AwsBoto3Error(
                    f"Unexpected error uploading {local_path.name} to s3://{bucket}/{key}: {e}"
                ) from e
    
    # Should not reach here, but handle it
    if last_error:
        raise AwsBoto3Error(f"Upload failed after {retries} attempts: {last_error}") from last_error


def s3_object_exists(*, bucket: str, key: str) -> bool:
    """Check if an S3 object exists.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key (path)
    
    Returns:
        True if object exists, False otherwise
    """
    client = _get_s3_client()
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        # Re-raise other errors
        raise


def s3_presign_url(*, bucket: str, key: str, expires_in_seconds: int) -> str:
    """Generate a presigned URL for an S3 object using boto3.
    
    Args:
        bucket: S3 bucket name
        key: S3 object key (path)
        expires_in_seconds: URL expiration time in seconds
    
    Returns:
        Presigned URL string
    
    Raises:
        AwsBoto3Error: If presigning fails
    """
    client = _get_presign_client()
    
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=expires_in_seconds
        )
        if not url:
            raise AwsBoto3Error(
                f"boto3 generate_presigned_url returned empty URL for s3://{bucket}/{key}.\n"
                f"This may indicate the object doesn't exist or you lack s3:GetObject permission."
            )
        return url
    except ClientError as e:
        guidance = _parse_boto3_error(e)
        error_msg = f"Failed to generate presigned URL for s3://{bucket}/{key}"
        if guidance:
            error_msg += f"\n\n{guidance}\n"
        error_msg += f"\nError: {e}"
        raise AwsBoto3Error(error_msg) from e
    except Exception as e:
        raise AwsBoto3Error(
            f"Unexpected error generating presigned URL for s3://{bucket}/{key}: {e}"
        ) from e

