#!/bin/bash
# Manual deployment script for GhostRoll image enhancement Lambda

set -e

BUCKET="photo-ingest-project"
FUNCTION_NAME="ghostroll-enhance-images"
STACK_NAME="ghostroll-enhance-images"

echo "Building Lambda package..."
cd "$(dirname "$0")"
sam build

echo "Deploying Lambda function..."
sam deploy \
  --stack-name "$STACK_NAME" \
  --parameter-overrides \
    S3Bucket="$BUCKET" \
    EnhancedPrefix=enhanced \
    EnhancementQuality=92 \
  --capabilities CAPABILITY_IAM \
  --resolve-s3 \
  --no-confirm-changeset

echo "Waiting for deployment to complete..."
aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" || \
aws cloudformation wait stack-update-complete --stack-name "$STACK_NAME"

echo "Getting Lambda function ARN..."
LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)
echo "Lambda ARN: $LAMBDA_ARN"

echo ""
echo "Configuring S3 bucket notification..."
echo "Note: This requires EventBridge to be enabled for the bucket."
echo ""
echo "To enable EventBridge for S3:"
echo "  aws s3api put-bucket-notification-configuration \\"
echo "    --bucket $BUCKET \\"
echo "    --notification-configuration '{\"EventBridgeConfiguration\": {}}'"
echo ""
echo "Or configure via AWS Console:"
echo "  S3 → $BUCKET → Properties → Event notifications → Edit"
echo "  Enable 'Send notifications to Amazon EventBridge'"
echo ""
echo "The Lambda function will automatically trigger on S3 uploads to sessions/*/share/*.jpg"

