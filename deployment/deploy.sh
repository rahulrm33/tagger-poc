#!/bin/bash

##########################################################################
# AWS Auto-Tagger Deployment Script
# Deploys Lambda function with S3 CloudTrail trigger
# ONE Lambda in ONE region handles ALL regions!
##########################################################################

set -e

# Get script directory for relative path resolution
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
FUNCTION_NAME="auto-tagger"
LAMBDA_ROLE_NAME="auto-tagger-lambda-role"
CLOUDTRAIL_NAME="auto-tagger-trail"
CLOUDTRAIL_BUCKET_BASE="auto-tagger-cloudtrail-logs-1"
LAMBDA_TIMEOUT=300  # 5 minutes for batch processing
LAMBDA_MEMORY=512   # More memory for S3 downloads

echo -e "${BLUE}AWS Auto-Tagger Deployment${NC}"
echo -e "${BLUE}========================================${NC}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}

echo -e "Account: ${ACCOUNT_ID}"
echo -e "Region: ${REGION}"
echo ""

# Step 1: Create S3 Bucket for CloudTrail
echo -e "\n${YELLOW}[1/7] Creating S3 Bucket for CloudTrail...${NC}"

FULL_BUCKET_NAME="${CLOUDTRAIL_BUCKET_BASE}-${ACCOUNT_ID}"

if aws s3 ls "s3://${FULL_BUCKET_NAME}" 2>/dev/null; then
    echo -e "${GREEN}✓ Bucket exists${NC}"
else
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket ${FULL_BUCKET_NAME} --region ${REGION}
    else
        aws s3api create-bucket --bucket ${FULL_BUCKET_NAME} --region ${REGION} --create-bucket-configuration LocationConstraint=${REGION}
    fi
    echo -e "${GREEN}✓ Bucket created${NC}"
fi

# Step 2: Configure S3 Bucket Policy for CloudTrail
echo -e "\n${YELLOW}[2/7] Configuring S3 Bucket Policy...${NC}"

cat > /tmp/cloudtrail-bucket-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AWSCloudTrailAclCheck",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudtrail.amazonaws.com"
      },
      "Action": "s3:GetBucketAcl",
      "Resource": "arn:aws:s3:::${FULL_BUCKET_NAME}"
    },
    {
      "Sid": "AWSCloudTrailWrite",
      "Effect": "Allow",
      "Principal": {
        "Service": "cloudtrail.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::${FULL_BUCKET_NAME}/AWSLogs/${ACCOUNT_ID}/*",
      "Condition": {
        "StringEquals": {
          "s3:x-amz-acl": "bucket-owner-full-control"
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-policy \
  --bucket ${FULL_BUCKET_NAME} \
  --policy file:///tmp/cloudtrail-bucket-policy.json
echo -e "${GREEN}✓ Done${NC}"

# Step 3: Create Lambda Execution Role with S3 permissions
echo -e "\n${YELLOW}[3/7] Creating Lambda Execution Role...${NC}"

cat > /tmp/lambda-trust-policy.json << 'EOF'
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
  --role-name ${LAMBDA_ROLE_NAME} \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
  --query 'Role.Arn' \
  --output text 2>/dev/null || \
  aws iam get-role \
    --role-name ${LAMBDA_ROLE_NAME} \
    --query 'Role.Arn' \
    --output text)
echo -e "${GREEN}✓ Done${NC}"

# Step 4: Attach Policies to Lambda Role (including S3 read)
echo -e "\n${YELLOW}[4/7] Attaching IAM Policies...${NC}"

# Enhanced policy with S3 read permissions
cat > /tmp/lambda-s3-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:${ACCOUNT_ID}:*"
    },
    {
      "Sid": "S3ReadCloudTrailLogs",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${FULL_BUCKET_NAME}",
        "arn:aws:s3:::${FULL_BUCKET_NAME}/*"
      ]
    },
    {
      "Sid": "TaggingPermissions",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateTags",
        "ec2:DescribeTags",
        "s3:PutBucketTagging",
        "s3:GetBucketTagging",
        "rds:AddTagsToResource",
        "rds:ListTagsForResource",
        "lambda:TagResource",
        "lambda:ListTags",
        "dynamodb:TagResource",
        "dynamodb:ListTagsOfResource",
        "sns:TagResource",
        "sns:ListTagsForResource",
        "sqs:TagQueue",
        "sqs:ListQueueTags"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name ${LAMBDA_ROLE_NAME} \
  --policy-name auto-tagger-s3-permissions \
  --policy-document file:///tmp/lambda-s3-policy.json
echo -e "${GREEN}✓ Done${NC}"
sleep 10

# Step 5: Package Lambda Function
echo -e "\n${YELLOW}[5/7] Packaging Lambda Function...${NC}"

LAMBDA_DIR="${PROJECT_ROOT}/lambda_function"
LAMBDA_ZIP="${PROJECT_ROOT}/lambda_function.zip"

rm -f ${LAMBDA_ZIP}

cd ${LAMBDA_DIR}
zip -j ${LAMBDA_ZIP} \
  lambda_handler.py \
  cloudtrail_parser.py \
  tag_manager.py \
  s3_cloudtrail_processor.py > /dev/null 2>&1

echo -e "${GREEN}✓ Done${NC}"

cd ${SCRIPT_DIR}

# Step 6: Create or Update Lambda Function
echo -e "\n${YELLOW}[6/7] Deploying Lambda Function...${NC}"

LAMBDA_ARN=$(aws lambda create-function \
  --function-name ${FUNCTION_NAME} \
  --runtime python3.11 \
  --role ${ROLE_ARN} \
  --handler lambda_handler.lambda_handler \
  --zip-file fileb://${LAMBDA_ZIP} \
  --timeout ${LAMBDA_TIMEOUT} \
  --memory-size ${LAMBDA_MEMORY} \
  --environment Variables='{ENVIRONMENT=production,TRIGGER_MODE=s3}' \
  --region ${REGION} \
  --query 'FunctionArn' \
  --output text 2>/dev/null || \
  aws lambda update-function-code \
    --function-name ${FUNCTION_NAME} \
    --zip-file fileb://${LAMBDA_ZIP} \
    --region ${REGION} \
    --query 'FunctionArn' \
    --output text)

echo -e "${GREEN}✓ Done${NC}"

if [ -z "$LAMBDA_ARN" ]; then
  LAMBDA_ARN=$(aws lambda get-function --function-name ${FUNCTION_NAME} --region ${REGION} --query 'Configuration.FunctionArn' --output text)
fi

aws lambda wait function-active --function-name ${FUNCTION_NAME} --region ${REGION}

# Step 7: Configure S3 to trigger Lambda
echo -e "\n${YELLOW}[7/7] Configuring S3 Event Notification...${NC}"

aws lambda remove-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowS3Invoke \
  --region ${REGION} 2>/dev/null || true

aws lambda add-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowS3Invoke \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::${FULL_BUCKET_NAME}" \
  --region ${REGION}

if [ $? -ne 0 ]; then
  echo -e "${RED}✗ Failed to add Lambda permission${NC}"
  exit 1
fi
echo -e "${GREEN}✓ Done${NC}"
sleep 15

# Create S3 notification configuration
cat > /tmp/s3-notification.json << EOF
{
  "LambdaFunctionConfigurations": [
    {
      "Id": "CloudTrailLogCreated",
      "LambdaFunctionArn": "${LAMBDA_ARN}",
      "Events": ["s3:ObjectCreated:*"],
      "Filter": {
        "Key": {
          "FilterRules": [
            {
              "Name": "suffix",
              "Value": ".json.gz"
            }
          ]
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-notification-configuration \
  --bucket ${FULL_BUCKET_NAME} \
  --notification-configuration file:///tmp/s3-notification.json
echo -e "${GREEN}✓ Done${NC}"

# Step 8: Create or Update CloudTrail
echo -e "\n${YELLOW}[Bonus] Setting up CloudTrail (if not exists)...${NC}"

TRAIL_ARN=$(aws cloudtrail create-trail \
  --name ${CLOUDTRAIL_NAME} \
  --s3-bucket-name ${FULL_BUCKET_NAME} \
  --is-multi-region-trail \
  --enable-log-file-validation \
  --region ${REGION} \
  --query 'TrailARN' \
  --output text 2>/dev/null || \
  aws cloudtrail describe-trails \
    --trail-name-list ${CLOUDTRAIL_NAME} \
    --query 'trailList[0].TrailARN' \
    --output text)

if [ "$TRAIL_ARN" != "None" ]; then
    aws cloudtrail start-logging --name ${CLOUDTRAIL_NAME} --region ${REGION} 2>/dev/null || true
    echo -e "${GREEN}✓ Done${NC}"
else
    echo -e "${YELLOW}⚠ CloudTrail may already exist${NC}"
fi

# Cleanup
rm -f /tmp/lambda-trust-policy.json
rm -f /tmp/lambda-s3-policy.json
rm -f /tmp/cloudtrail-bucket-policy.json
rm -f /tmp/s3-notification.json

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "Lambda: ${FUNCTION_NAME}"
echo -e "Region: ${REGION}"
echo -e "Bucket: ${FULL_BUCKET_NAME}"
echo -e "\nMonitor logs:"
echo -e "  aws logs tail /aws/lambda/${FUNCTION_NAME} --follow"
echo ""

