#!/bin/bash
# Create Lambda function directly using AWS CLI

set -e

BUCKET="photo-ingest-project"
FUNCTION_NAME="ghostroll-enhance-images"
ROLE_NAME="ghostroll-lambda-role"
ZIP_FILE="lambda-deployment.zip"

echo "Creating IAM role for Lambda..."
# Check if role exists
if aws iam get-role --role-name "$ROLE_NAME" &>/dev/null; then
    echo "Role $ROLE_NAME already exists"
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
else
    echo "Creating role $ROLE_NAME..."
    # Create trust policy
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF
    
    ROLE_ARN=$(aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document file:///tmp/trust-policy.json \
        --query 'Role.Arn' --output text)
    
    echo "Attaching policies..."
    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # Create inline policy for S3 access
    cat > /tmp/s3-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:HeadObject"
      ],
      "Resource": "arn:aws:s3:::$BUCKET/*"
    }
  ]
}
EOF
    
    aws iam put-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-name S3Access \
        --policy-document file:///tmp/s3-policy.json
    
    echo "Waiting for role to be ready..."
    sleep 5
fi

echo "Role ARN: $ROLE_ARN"

echo "Creating Lambda function..."
if aws lambda get-function --function-name "$FUNCTION_NAME" &>/dev/null; then
    echo "Function exists, updating code..."
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://$ZIP_FILE" \
        --output json | jq -r '.FunctionArn'
    
    echo "Updating configuration..."
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --timeout 300 \
        --memory-size 1024 \
        --environment "Variables={S3_BUCKET=$BUCKET,ENHANCED_PREFIX=enhanced,ENHANCEMENT_QUALITY=92}" \
        --output json | jq -r '.FunctionArn'
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.11 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file "fileb://$ZIP_FILE" \
        --timeout 300 \
        --memory-size 1024 \
        --description "Automatically enhance lighting of uploaded GhostRoll images" \
        --environment "Variables={S3_BUCKET=$BUCKET,ENHANCED_PREFIX=enhanced,ENHANCEMENT_QUALITY=92}" \
        --output json | jq -r '.FunctionArn'
fi

echo ""
echo "Lambda function deployed successfully!"
echo ""
echo "Next steps:"
echo "1. Enable EventBridge for S3 bucket:"
echo "   aws s3api put-bucket-notification-configuration \\"
echo "     --bucket $BUCKET \\"
echo "     --notification-configuration '{\"EventBridgeConfiguration\": {}}'"
echo ""
echo "2. Or configure S3 to invoke Lambda directly (see DEPLOYMENT.md)"

