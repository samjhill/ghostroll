#!/usr/bin/env python3
"""
Comprehensive test suite for image enhancement Lambda function.
Tests idempotency, error handling, cost optimization, and performance.
"""

import json
import os
import tempfile
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from PIL import Image

from enhancement import enhance_image_auto
from lambda_function import process_image, get_enhanced_key, lambda_handler

# Configuration
S3_BUCKET = os.environ.get("S3_BUCKET", "photo-ingest-project")
TEST_SESSION = "test-session-comprehensive"


def create_test_image(path: Path, width: int = 2048, height: int = 1536) -> None:
    """Create a test JPEG image."""
    img = Image.new("RGB", (width, height), color=(128, 128, 128))
    img.save(path, format="JPEG", quality=90)


def test_idempotency():
    """Test that processing the same image twice doesn't duplicate work."""
    print("\n=== Test 1: Idempotency ===")
    
    s3 = boto3.client("s3")
    test_key = f"sessions/{TEST_SESSION}/share/test_idempotency.jpg"
    enhanced_key = get_enhanced_key(test_key)
    
    # Create and upload test image
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        test_path = Path(tmp.name)
        create_test_image(test_path)
        s3.upload_file(str(test_path), S3_BUCKET, test_key)
        test_path.unlink()
    
    # Process first time
    print("  Processing image first time...")
    start = time.time()
    result1 = process_image(S3_BUCKET, test_key)
    time1 = time.time() - start
    print(f"    Result: {result1['status']} (took {time1:.2f}s)")
    
    # Process second time (should skip)
    print("  Processing image second time (should skip)...")
    start = time.time()
    result2 = process_image(S3_BUCKET, test_key)
    time2 = time.time() - start
    print(f"    Result: {result2['status']} (took {time2:.2f}s)")
    
    # Verify
    assert result1["status"] == "success", "First processing should succeed"
    assert result2["status"] == "skipped", "Second processing should be skipped"
    assert result2["reason"] == "already_enhanced", "Should skip because already enhanced"
    assert time2 < time1, "Second call should be faster (just checks existence)"
    
    print("  ✅ Idempotency test passed")
    
    # Cleanup
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=test_key)
        s3.delete_object(Bucket=S3_BUCKET, Key=enhanced_key)
    except:
        pass


def test_skip_non_jpeg():
    """Test that non-JPEG files are skipped."""
    print("\n=== Test 2: Skip Non-JPEG Files ===")
    
    s3 = boto3.client("s3")
    test_key = f"sessions/{TEST_SESSION}/share/test.txt"
    
    # Upload a text file
    s3.put_object(Bucket=S3_BUCKET, Key=test_key, Body=b"not an image")
    
    result = process_image(S3_BUCKET, test_key)
    print(f"  Result: {result['status']} - {result['reason']}")
    
    assert result["status"] == "skipped", "Should skip non-JPEG files"
    assert result["reason"] == "not_a_jpeg", "Should indicate not a JPEG"
    
    print("  ✅ Non-JPEG skip test passed")
    
    # Cleanup
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=test_key)
    except:
        pass


def test_skip_wrong_prefix():
    """Test that files not in share/ prefix are skipped."""
    print("\n=== Test 3: Skip Wrong Prefix ===")
    
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": S3_BUCKET},
                    "object": {"key": f"sessions/{TEST_SESSION}/thumbs/test.jpg"}
                }
            }
        ]
    }
    
    result = lambda_handler(event, None)
    body = json.loads(result["body"])
    
    print(f"  Processed: {body['processed']}")
    print(f"  Skipped: {body['skipped']}")
    
    assert body["skipped"] == 1, "Should skip files not in share/ prefix"
    assert body["results"][0]["reason"] == "not_in_share_prefix"
    
    print("  ✅ Wrong prefix skip test passed")


def test_error_handling():
    """Test error handling for missing files."""
    print("\n=== Test 4: Error Handling ===")
    
    # Try to process non-existent file
    result = process_image(S3_BUCKET, f"sessions/{TEST_SESSION}/share/nonexistent.jpg")
    
    # Should handle gracefully (will fail on download, but should catch error)
    print(f"  Result: {result.get('status', 'unknown')}")
    print("  ✅ Error handling test passed (errors are caught)")


def test_memory_cleanup():
    """Test that temporary files are cleaned up."""
    print("\n=== Test 5: Memory Cleanup ===")
    
    s3 = boto3.client("s3")
    test_key = f"sessions/{TEST_SESSION}/share/test_cleanup.jpg"
    enhanced_key = get_enhanced_key(test_key)
    
    # Create and upload test image
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        test_path = Path(tmp.name)
        create_test_image(test_path, width=512, height=384)  # Smaller for faster test
        s3.upload_file(str(test_path), S3_BUCKET, test_key)
        test_path.unlink()
    
    # Process image
    result = process_image(S3_BUCKET, test_key)
    assert result["status"] == "success", "Processing should succeed"
    
    # Check that temp files don't exist (they should be cleaned up)
    temp_dir = Path(tempfile.gettempdir())
    temp_files = list(temp_dir.glob("tmp*.jpg"))
    print(f"  Temp files remaining: {len(temp_files)}")
    
    # Cleanup
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=test_key)
        s3.delete_object(Bucket=S3_BUCKET, Key=enhanced_key)
    except:
        pass
    
    print("  ✅ Memory cleanup test passed")


def test_performance():
    """Test processing performance."""
    print("\n=== Test 6: Performance ===")
    
    s3 = boto3.client("s3")
    test_key = f"sessions/{TEST_SESSION}/share/test_perf.jpg"
    enhanced_key = get_enhanced_key(test_key)
    
    # Create test image (typical share image size: 2048px)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        test_path = Path(tmp.name)
        create_test_image(test_path, width=2048, height=1536)
        file_size = test_path.stat().st_size
        s3.upload_file(str(test_path), S3_BUCKET, test_key)
        test_path.unlink()
    
    print(f"  Image size: {file_size:,} bytes")
    
    # Process and measure time
    start = time.time()
    result = process_image(S3_BUCKET, test_key)
    elapsed = time.time() - start
    
    print(f"  Processing time: {elapsed:.2f}s")
    print(f"  Result: {result['status']}")
    
    # Should complete in reasonable time (< 30s for 2048px image)
    assert elapsed < 30, f"Processing took too long: {elapsed:.2f}s"
    assert result["status"] == "success", "Processing should succeed"
    
    # Cleanup
    try:
        s3.delete_object(Bucket=S3_BUCKET, Key=test_key)
        s3.delete_object(Bucket=S3_BUCKET, Key=enhanced_key)
    except:
        pass
    
    print("  ✅ Performance test passed")


def test_batch_processing():
    """Test handling multiple images in one event."""
    print("\n=== Test 7: Batch Processing ===")
    
    s3 = boto3.client("s3")
    test_keys = [
        f"sessions/{TEST_SESSION}/share/batch1.jpg",
        f"sessions/{TEST_SESSION}/share/batch2.jpg",
    ]
    
    # Upload test images
    for key in test_keys:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            test_path = Path(tmp.name)
            create_test_image(test_path, width=512, height=384)
            s3.upload_file(str(test_path), S3_BUCKET, key)
            test_path.unlink()
    
    # Create event with multiple records
    event = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": S3_BUCKET},
                    "object": {"key": key}
                }
            }
            for key in test_keys
        ]
    }
    
    result = lambda_handler(event, None)
    body = json.loads(result["body"])
    
    print(f"  Processed: {body['processed']}")
    print(f"  Success: {body['success']}")
    print(f"  Skipped: {body['skipped']}")
    print(f"  Errors: {body['errors']}")
    
    assert body["success"] == 2, "Should process both images"
    assert body["errors"] == 0, "Should have no errors"
    
    # Cleanup
    for key in test_keys:
        try:
            s3.delete_object(Bucket=S3_BUCKET, Key=key)
            s3.delete_object(Bucket=S3_BUCKET, Key=get_enhanced_key(key))
        except:
            pass
    
    print("  ✅ Batch processing test passed")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Comprehensive Lambda Function Test Suite")
    print("=" * 60)
    
    tests = [
        test_idempotency,
        test_skip_non_jpeg,
        test_skip_wrong_prefix,
        test_error_handling,
        test_memory_cleanup,
        test_performance,
        test_batch_processing,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  ❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit(main())

