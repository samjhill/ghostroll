# Post-Upload Image Enhancement - Implementation Summary

## Overview

This implementation adds automatic lighting enhancement to GhostRoll images after they're uploaded to S3. The enhancement is similar to Lightroom's auto-settings button and applies automatic adjustments for exposure, contrast, highlights, and shadows.

## Architecture

```
┌─────────────────┐
│  GhostRoll      │
│  Pipeline       │
└────────┬────────┘
         │ Uploads share images
         ▼
┌─────────────────┐
│  S3 Bucket      │
│  sessions/.../  │
│  share/IMG.jpg  │
└────────┬────────┘
         │ S3 Event (EventBridge)
         ▼
┌─────────────────┐
│  Lambda Function│
│  enhance-images │
└────────┬────────┘
         │ Downloads, enhances, uploads
         ▼
┌─────────────────┐
│  S3 Bucket      │
│  sessions/.../  │
│  enhanced/IMG.jpg
└─────────────────┘
```

## Files Created

### Core Lambda Function
- `enhance-images/lambda_function.py` - Main Lambda handler
- `enhance-images/enhancement.py` - Image enhancement algorithms
- `enhance-images/requirements.txt` - Python dependencies

### Infrastructure
- `template.yaml` - AWS SAM template for deployment
- `samconfig.toml.example` - Example SAM configuration

### Documentation
- `README.md` - Main documentation
- `DEPLOYMENT.md` - Deployment instructions
- `IMPLEMENTATION_SUMMARY.md` - This file

### Testing
- `enhance-images/events/test-s3-event.json` - Test event for local testing

## Enhancement Algorithm

The enhancement applies four automatic adjustments:

1. **Auto Exposure**: Analyzes image histogram to determine optimal brightness
   - Calculates weighted mean of pixel values
   - Adjusts exposure to target mean (128, slightly brighter than middle gray)
   - Range: -2 to +2 EV

2. **Auto Contrast**: Finds optimal black and white points
   - Clips 0.5% of darkest pixels to black
   - Clips 0.5% of brightest pixels to white
   - Maps remaining range to full 0-255

3. **Auto Highlights**: Reduces overexposed areas
   - Detects pixels > 200 (very bright)
   - If >15% of image is very bright, reduces highlights
   - Range: 0 to +50 (positive = reduce highlights)

4. **Auto Shadows**: Brightens underexposed areas
   - Detects pixels < 50 (very dark)
   - If >20% of image is very dark, brightens shadows
   - Range: 0 to +50 (positive = brighten shadows)

## S3 Structure

Before enhancement:
```
sessions/{session_id}/
  ├── share/IMG_001.jpg
  ├── thumbs/IMG_001.jpg
  └── index.html
```

After enhancement:
```
sessions/{session_id}/
  ├── share/IMG_001.jpg        (original)
  ├── enhanced/IMG_001.jpg    (enhanced - new)
  ├── thumbs/IMG_001.jpg
  └── index.html
```

## Integration Points

### Current State
- ✅ Lambda function processes images automatically
- ✅ Enhanced images stored in `enhanced/` prefix
- ✅ No changes required to existing pipeline

### Optional Future Enhancements

1. **Gallery Integration**: Update gallery to prefer enhanced images
   ```python
   # In gallery.py or pipeline.py
   def get_image_url(session_id, image_name, prefer_enhanced=True):
       if prefer_enhanced:
           enhanced_key = f"sessions/{session_id}/enhanced/{image_name}"
           if s3_object_exists(enhanced_key):
               return presign_url(enhanced_key)
       # Fallback to share image
       share_key = f"sessions/{session_id}/share/{image_name}"
       return presign_url(share_key)
   ```

2. **Progressive Enhancement**: Update gallery as images are enhanced
   - Poll for enhanced images
   - Update gallery HTML when new enhanced images are available

3. **User Toggle**: Allow users to switch between original and enhanced
   - Add toggle button in gallery
   - Store preference in URL parameter or localStorage

## Configuration

### Environment Variables (Lambda)
- `S3_BUCKET` - S3 bucket name (required)
- `ENHANCED_PREFIX` - Prefix for enhanced images (default: `enhanced`)
- `ENHANCEMENT_QUALITY` - JPEG quality 1-100 (default: `92`)

### Lambda Settings
- **Memory**: 1024 MB (recommended: 2048 MB for large images)
- **Timeout**: 300 seconds (5 minutes)
- **Runtime**: Python 3.11

## Cost Estimate

For 1,000 images/month:
- **Lambda compute**: ~$0.17 (10s per image at 1024 MB)
- **Lambda invocations**: ~$0.0002
- **S3 storage**: Depends on image sizes (~2-5 MB per enhanced image)
- **S3 requests**: ~$0.005

**Total**: ~$0.20-0.50 per 1,000 images (plus S3 storage)

## Deployment Steps

1. **Deploy Lambda**:
   ```bash
   cd aws-lambda
   sam build
   sam deploy --guided
   ```

2. **Configure S3 EventBridge** (see `DEPLOYMENT.md`)

3. **Test**:
   ```bash
   # Upload test image
   aws s3 cp test.jpg s3://bucket/sessions/test/share/test.jpg
   
   # Check logs
   aws logs tail /aws/lambda/ghostroll-enhance-images --follow
   
   # Verify enhanced image
   aws s3 ls s3://bucket/sessions/test/enhanced/
   ```

## Testing

### Local Testing
```bash
cd enhance-images
pip install -r requirements.txt
python -c "
from enhancement import enhance_image_auto
from PIL import Image

img = Image.open('test.jpg')
enhanced = enhance_image_auto(img)
enhanced.save('test-enhanced.jpg')
"
```

### Lambda Testing
```bash
sam local invoke EnhanceImagesFunction \
  --event enhance-images/events/test-s3-event.json
```

## Monitoring

### CloudWatch Metrics
- Lambda invocations
- Lambda errors
- Lambda duration
- Lambda memory usage

### CloudWatch Logs
- Processing status per image
- Errors and skip reasons
- Performance metrics

## Known Limitations

1. **Only processes JPEGs**: RAW files and other formats are skipped
2. **Processes share images**: Works on 2048px images (not originals)
3. **No user control**: Enhancement is automatic (no strength adjustment)
4. **Sequential processing**: One image per Lambda invocation

## Future Improvements

- [ ] Support for RAW files
- [ ] Batch processing (multiple images per invocation)
- [ ] User-configurable enhancement strength
- [ ] Different enhancement presets
- [ ] Progressive gallery updates
- [ ] Webhook notifications
- [ ] Cost optimization (reserved concurrency, etc.)

## Troubleshooting

See `DEPLOYMENT.md` for detailed troubleshooting steps.

Common issues:
- Lambda not triggering → Check S3 EventBridge configuration
- Out of memory → Increase Lambda memory
- Import errors → Use Lambda Layer for Pillow/numpy
- Timeout → Increase timeout or check image sizes

