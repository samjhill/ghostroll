# GhostRoll Post-Upload Image Enhancement

This directory contains an AWS Lambda function that automatically enhances uploaded images with automatic lighting adjustments, similar to Lightroom's auto-settings button.

## Overview

When images are uploaded to S3 in the `share/` prefix, this Lambda function:
1. Downloads the image
2. Applies automatic lighting enhancements (exposure, contrast, highlights, shadows)
3. Uploads the enhanced version to the `enhanced/` prefix

The enhanced images can then be used by the gallery (with fallback to original share images if enhancement isn't available).

## Architecture

```
S3 Upload (share/IMG_001.jpg)
    ↓
S3 EventBridge Rule
    ↓
Lambda Function (ghostroll-enhance-images)
    ↓
Download → Enhance → Upload (enhanced/IMG_001.jpg)
```

## Enhancement Algorithm

The enhancement applies automatic adjustments similar to Lightroom's auto-settings:

1. **Auto Exposure**: Analyzes histogram to determine optimal brightness
2. **Auto Contrast**: Finds optimal black and white points
3. **Auto Highlights/Shadows**: Adjusts bright and dark areas

The algorithm is histogram-based and works well for most photos without over-processing.

## Deployment

### Prerequisites

- AWS CLI configured
- AWS SAM CLI installed (`pip install aws-sam-cli`)
- Python 3.11+ (for local testing)

### Deploy with SAM

```bash
cd aws-lambda

# Build the Lambda package
sam build

# Deploy (first time - creates stack)
sam deploy --guided

# Or deploy with parameters
sam deploy \
  --parameter-overrides \
    S3Bucket=your-bucket-name \
    EnhancedPrefix=enhanced \
    EnhancementQuality=92
```

### Manual Deployment

If you prefer to deploy manually:

1. **Create Lambda Layer** (for Pillow + numpy - recommended):
   ```bash
   # Create a layer with Pillow and numpy
   mkdir -p layer/python
   pip install -r enhance-images/requirements.txt -t layer/python/
   cd layer
   zip -r ../pillow-layer.zip .
   cd ..
   
   # Upload to S3 and create layer
   aws s3 cp pillow-layer.zip s3://your-bucket/layers/
   aws lambda publish-layer-version \
     --layer-name pillow-numpy \
     --content S3Bucket=your-bucket,S3Key=layers/pillow-layer.zip \
     --compatible-runtimes python3.11
   ```

2. **Package Lambda function**:
   ```bash
   cd enhance-images
   zip -r ../enhance-images.zip .
   ```

3. **Create Lambda function** (via AWS Console or CLI):
   - Runtime: Python 3.11
   - Handler: `lambda_function.lambda_handler`
   - Memory: 1024 MB
   - Timeout: 300 seconds
   - Environment variables:
     - `S3_BUCKET`: your bucket name
     - `ENHANCED_PREFIX`: `enhanced`
     - `ENHANCEMENT_QUALITY`: `92`

4. **Set up S3 trigger**:
   - Event type: `s3:ObjectCreated:*`
   - Prefix: `sessions/`
   - Suffix: `.jpg`

5. **IAM Permissions**:
   The Lambda needs:
   - `s3:GetObject` on the bucket
   - `s3:PutObject` on the bucket
   - `s3:HeadObject` on the bucket (to check if enhanced version exists)

## Configuration

### Environment Variables

- `S3_BUCKET`: S3 bucket name (required)
- `ENHANCED_PREFIX`: Prefix for enhanced images (default: `enhanced`)
- `ENHANCEMENT_QUALITY`: JPEG quality 1-100 (default: `92`)

### Lambda Settings

- **Memory**: 1024 MB (Pillow and numpy need memory)
- **Timeout**: 300 seconds (5 minutes for large images)
- **Runtime**: Python 3.11

## Cost Estimation

Approximate costs (us-east-1, as of 2024):
- **Lambda invocations**: $0.20 per 1M requests
- **Compute time**: $0.0000166667 per GB-second
  - Average: ~2 seconds per image at 1024 MB
  - Cost per image: ~$0.000033
- **S3 storage**: Standard S3 pricing for enhanced images (~$0.023/GB/month)
- **S3 requests**: $0.005 per 1,000 PUT requests

**Example**: 1,000 images/month
- Lambda: ~$0.033 (compute) + $0.0002 (invocations) = **~$0.033**
- S3 storage: ~$0.009 (0.4 MB avg per image)
- S3 requests: ~$0.005

**Total: ~$0.048 per 1,000 images** (or **$0.000048 per image**)

### Cost Optimizations

The Lambda function includes several cost optimizations:

1. **Idempotency**: Skips processing if enhanced version already exists (prevents duplicate costs)
2. **Early Exit**: Skips non-JPEG files immediately (saves compute time)
3. **Prefix Filtering**: Only processes files in `share/` prefix (reduces unnecessary invocations)
4. **Efficient Error Handling**: Catches errors early to avoid wasted processing

With these optimizations, duplicate uploads or re-processing won't incur additional costs.

## Testing

### Comprehensive Test Suite

A full test suite is included to verify functionality and cost optimizations:

```bash
cd enhance-images
python3 test_comprehensive.py
```

Tests include:
- ✅ Idempotency (prevents duplicate processing)
- ✅ Skip non-JPEG files (early exit)
- ✅ Skip wrong prefix (filtering)
- ✅ Error handling (graceful failures)
- ✅ Memory cleanup (no leaks)
- ✅ Performance (completes in <30s)
- ✅ Batch processing (multiple images)

### Local Testing

```bash
# Install dependencies
cd enhance-images
pip install -r requirements.txt

# Test the enhancement function
python -c "
from enhancement import enhance_image_auto
from PIL import Image

img = Image.open('test-image.jpg')
enhanced = enhance_image_auto(img)
enhanced.save('test-enhanced.jpg')
"
```

### Test Lambda Locally

```bash
# Using SAM CLI
sam local invoke EnhanceImagesFunction \
  --event events/test-s3-event.json
```

Create `events/test-s3-event.json`:
```json
{
  "Records": [
    {
      "s3": {
        "bucket": {"name": "your-bucket"},
        "object": {"key": "sessions/shoot-2024-01-01_120000/share/IMG_001.jpg"}
      }
    }
  ]
}
```

### Cost Analysis

Run cost analysis to understand pricing:

```bash
cd enhance-images
python3 cost_analysis.py
```

This shows:
- Current costs per image
- Optimization opportunities
- Potential savings

## Monitoring

### CloudWatch Metrics

Monitor:
- Lambda invocations
- Lambda errors
- Lambda duration
- S3 object counts in `enhanced/` prefix

### CloudWatch Logs

Lambda logs include:
- Processing status for each image
- Errors (if any)
- Skip reasons (already enhanced, not a JPEG, etc.)

## Troubleshooting

### Lambda timeout

- Increase memory (more memory = faster processing)
- Increase timeout (for very large images)
- Consider using container image instead of zip (faster cold starts)

### Out of memory

- Increase Lambda memory allocation
- Process smaller images (already resized share images should be fine)

### Pillow import errors

- Use a Lambda Layer with pre-compiled Pillow
- Or use a container image with Pillow pre-installed

### S3 permissions

- Ensure Lambda execution role has `s3:GetObject`, `s3:PutObject`, `s3:HeadObject`
- Check bucket policy allows Lambda access

## Integration with Gallery

The enhanced images are stored at:
```
sessions/{session_id}/enhanced/{image_name}.jpg
```

### Gallery Toggle Feature

The gallery automatically detects enhanced images and includes a toggle button:

1. **Automatic Detection**: Gallery checks for enhanced versions when generating presigned URLs
2. **Toggle Button**: Appears in gallery header when enhanced images are available
3. **User Control**: Click to switch between "✨ Enhanced" and "📷 Original"
4. **Persistent Preference**: User's choice saved in browser localStorage
5. **Fallback**: Uses original image if enhanced version not available

The toggle is implemented in `ghostroll/gallery.py` and works automatically - no additional configuration needed.

### How It Works

1. Pipeline checks for enhanced images when presigning URLs
2. Gallery HTML includes both original and enhanced URLs as data attributes
3. JavaScript handles switching based on user preference
4. Lightbox displays the selected version (enhanced or original)

## Testing and Quality Assurance

See `TESTING_AND_OPTIMIZATION.md` for comprehensive test results and optimization details.

### Test Results Summary

- ✅ All 7 Lambda function tests passing
- ✅ Gallery integration verified
- ✅ Cost optimizations implemented
- ✅ Performance within targets (<2s average)
- ✅ Error handling comprehensive
- ✅ Memory management verified (no leaks)

### Cost Analysis

- Current cost: **~$0.000048 per image**
- Optimizations save ~50% on duplicate processing
- See `enhance-images/cost_analysis.py` for detailed breakdown

## Future Enhancements

Possible improvements:
- [ ] Support for RAW files (requires more processing)
- [ ] Memory optimization (reduce to 512MB for cost savings)
- [ ] User-configurable enhancement strength
- [ ] Different enhancement presets (vibrant, natural, etc.)
- [ ] Progressive enhancement (update gallery as images are enhanced)
- [ ] Webhook notification when enhancement completes
- [ ] Reserved concurrency for high-volume usage

