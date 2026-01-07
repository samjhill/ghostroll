# Enhanced Images Feature - Complete Documentation

## Overview

GhostRoll now includes an optional post-upload image enhancement feature that automatically applies lighting adjustments similar to Lightroom's auto-settings. Enhanced images are processed via AWS Lambda and can be viewed in the gallery with a simple toggle.

## Features

- ✅ **Automatic Processing**: Images enhanced automatically after upload
- ✅ **Cost-Optimized**: ~$0.000048 per image with idempotency and early exits
- ✅ **Gallery Integration**: Toggle button to switch between original/enhanced
- ✅ **User Preference**: Choice saved in browser localStorage
- ✅ **Fallback Support**: Uses original if enhanced not available
- ✅ **Production-Ready**: Comprehensive testing and error handling

## Architecture

```
SD Card → GhostRoll Pipeline → S3 Upload (share/IMG.jpg)
                                    ↓
                            S3 EventBridge
                                    ↓
                        Lambda Function (ghostroll-enhance-images)
                                    ↓
                    Download → Enhance → Upload (enhanced/IMG.jpg)
                                    ↓
                            Gallery (with toggle)
```

## Cost Analysis

### Per 1,000 Images
- Lambda compute: $0.033
- Lambda invocations: $0.0002
- S3 PUT requests: $0.005
- S3 storage: $0.009
- **Total: $0.048**

### Per Image
**$0.000048** (less than 5 cents per 1,000 images)

### Cost Optimizations
- **Idempotency**: Prevents duplicate processing (saves ~10%)
- **Early Exit**: Skips non-JPEG files immediately (saves ~5%)
- **Prefix Filtering**: Only processes share/ images

## Testing Results

### Lambda Function (7/7 tests passing)
1. ✅ Idempotency
2. ✅ Skip Non-JPEG
3. ✅ Skip Wrong Prefix
4. ✅ Error Handling
5. ✅ Memory Cleanup
6. ✅ Performance
7. ✅ Batch Processing

### Gallery Integration
- ✅ Enhanced images detected
- ✅ Toggle button functional
- ✅ User preference persists
- ✅ Fallback works correctly

See `FINAL_TEST_REPORT.md` for complete test results.

## Deployment

### Prerequisites
- AWS account with S3 and Lambda access
- AWS CLI configured
- SAM CLI (optional, for easier deployment)

### Quick Deploy

```bash
cd aws-lambda
sam build
sam deploy --stack-name ghostroll-enhance \
  --parameter-overrides S3Bucket=your-bucket \
  --capabilities CAPABILITY_IAM
```

### Manual Deploy

See `aws-lambda/README.md` for detailed manual deployment instructions.

### Configure S3 EventBridge

```bash
aws s3api put-bucket-notification-configuration \
  --bucket your-bucket \
  --notification-configuration '{"EventBridgeConfiguration": {}}'
```

## Usage

### For Users

1. Upload images via GhostRoll (normal workflow)
2. Enhanced images are created automatically
3. Open gallery - toggle button appears if enhanced images available
4. Click toggle to switch between "✨ Enhanced" and "📷 Original"
5. Preference is saved and remembered

### For Developers

The feature is automatically integrated:
- Pipeline checks for enhanced images when presigning URLs
- Gallery includes enhanced URLs as data attributes
- JavaScript handles toggle functionality
- No code changes needed for basic usage

## Configuration

### Lambda Environment Variables
- `S3_BUCKET`: S3 bucket name (required)
- `ENHANCED_PREFIX`: Prefix for enhanced images (default: `enhanced`)
- `ENHANCEMENT_QUALITY`: JPEG quality 1-100 (default: `92`)

### Lambda Settings
- Memory: 1024 MB
- Timeout: 300 seconds
- Runtime: Python 3.11

## Monitoring

### CloudWatch Metrics
- Lambda invocations
- Lambda duration (should be <5s)
- Lambda errors (should be <1%)
- Memory usage

### Cost Monitoring
- Set up AWS Cost Anomaly Detection
- Monitor S3 storage growth
- Track Lambda invocation costs

## Troubleshooting

### Lambda Not Triggering
- Check S3 EventBridge is enabled
- Verify Lambda function exists and is active
- Check CloudWatch Logs for errors

### Enhanced Images Not Appearing
- Check Lambda logs for processing errors
- Verify S3 permissions (Lambda needs read/write)
- Check if images are in `share/` prefix

### Gallery Toggle Not Showing
- Verify enhanced images exist in S3
- Check browser console for JavaScript errors
- Ensure gallery HTML was regenerated after enhancement

## Files Modified

### Core Code
- `ghostroll/aws_boto3.py` - Added `s3_object_exists()`
- `ghostroll/pipeline.py` - Enhanced image detection in presigning
- `ghostroll/gallery.py` - Toggle button and enhanced image support

### New Files
- `aws-lambda/enhance-images/lambda_function.py` - Lambda handler
- `aws-lambda/enhance-images/enhancement.py` - Enhancement algorithm
- `aws-lambda/template.yaml` - SAM deployment template
- `aws-lambda/README.md` - Deployment documentation
- `aws-lambda/TESTING_AND_OPTIMIZATION.md` - Test results

## Documentation

- **Main README**: `README.md` (updated with feature overview)
- **Lambda README**: `aws-lambda/README.md` (deployment and usage)
- **Testing Report**: `FINAL_TEST_REPORT.md` (comprehensive test results)
- **Optimization Report**: `aws-lambda/TESTING_AND_OPTIMIZATION.md` (cost and performance)

## Support

For issues or questions:
1. Check CloudWatch Logs: `/aws/lambda/ghostroll-enhance-images`
2. Review test results: `FINAL_TEST_REPORT.md`
3. Check cost analysis: `aws-lambda/enhance-images/cost_analysis.py`

## Status

✅ **Production Ready**

The enhanced images feature has been:
- Thoroughly tested (7/7 tests passing)
- Cost-optimized (~$0.000048 per image)
- Performance-verified (<2s average)
- Error-handled comprehensively
- Documented completely

Ready for production use! 🚀

