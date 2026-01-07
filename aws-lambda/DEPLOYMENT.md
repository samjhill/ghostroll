# Deployment Guide

## Quick Start

1. **Install SAM CLI**:
   ```bash
   pip install aws-sam-cli
   ```

2. **Configure S3 bucket notifications** (required for EventBridge):
   
   The SAM template uses EventBridge, but S3 needs to be configured to send events to EventBridge.
   
   Option A: Use AWS Console
   - Go to S3 → Your bucket → Properties → Event notifications
   - Create event notification:
     - Event types: `All object create events`
     - Prefix: `sessions/`
     - Suffix: `.jpg`
     - Destination: `EventBridge` (enable it if not already enabled)

   Option B: Use AWS CLI
   ```bash
   aws s3api put-bucket-notification-configuration \
     --bucket your-bucket-name \
     --notification-configuration '{
       "EventBridgeConfiguration": {}
     }'
   ```

3. **Deploy Lambda**:
   ```bash
   cd aws-lambda
   sam build
   sam deploy --guided
   ```

## Manual S3 Event Configuration

If EventBridge isn't available, you can configure S3 to invoke Lambda directly:

```bash
# Get Lambda function ARN (after deployment)
LAMBDA_ARN=$(aws lambda get-function --function-name ghostroll-enhance-images --query 'Configuration.FunctionArn' --output text)

# Add permission for S3 to invoke Lambda
aws lambda add-permission \
  --function-name ghostroll-enhance-images \
  --principal s3.amazonaws.com \
  --statement-id s3-trigger \
  --action "lambda:InvokeFunction" \
  --source-arn "arn:aws:s3:::your-bucket-name"

# Configure S3 bucket notification
aws s3api put-bucket-notification-configuration \
  --bucket your-bucket-name \
  --notification-configuration "{
    \"LambdaFunctionConfigurations\": [{
      \"Id\": \"ghostroll-enhance-trigger\",
      \"LambdaFunctionArn\": \"$LAMBDA_ARN\",
      \"Events\": [\"s3:ObjectCreated:*\"],
      \"Filter\": {
        \"Key\": {
          \"FilterRules\": [
            {\"Name\": \"prefix\", \"Value\": \"sessions/\"},
            {\"Name\": \"suffix\", \"Value\": \".jpg\"}
          ]
        }
      }
    }]
  }"
```

## Using Lambda Layer (Recommended)

Pillow and numpy are large. For faster cold starts, use a Lambda Layer:

1. **Create layer**:
   ```bash
   mkdir -p layer/python
   pip install Pillow numpy -t layer/python/
   cd layer
   zip -r ../pillow-numpy-layer.zip .
   cd ..
   ```

2. **Upload and create layer**:
   ```bash
   aws s3 cp pillow-numpy-layer.zip s3://your-bucket/layers/
   
   aws lambda publish-layer-version \
     --layer-name ghostroll-pillow-numpy \
     --content S3Bucket=your-bucket,S3Key=layers/pillow-numpy-layer.zip \
     --compatible-runtimes python3.11
   ```

3. **Update SAM template** to reference the layer:
   ```yaml
   Layers:
     - !Ref PillowNumpyLayer
   ```

## Testing After Deployment

1. **Upload a test image**:
   ```bash
   aws s3 cp test-image.jpg s3://your-bucket/sessions/test-session/share/test.jpg
   ```

2. **Check Lambda logs**:
   ```bash
   aws logs tail /aws/lambda/ghostroll-enhance-images --follow
   ```

3. **Verify enhanced image exists**:
   ```bash
   aws s3 ls s3://your-bucket/sessions/test-session/enhanced/
   ```

## Troubleshooting

### Lambda not triggering

- Check S3 bucket notification configuration
- Verify EventBridge is enabled for the bucket
- Check Lambda function permissions (CloudWatch Logs)

### Out of memory errors

- Increase Lambda memory (edit `template.yaml`, set `MemorySize: 2048`)

### Import errors (Pillow/numpy)

- Use a Lambda Layer (see above)
- Or increase package size limit (use container image instead)

### Timeout errors

- Increase timeout (edit `template.yaml`, set `Timeout: 600`)
- Check image sizes (should be ~2048px max from share images)

