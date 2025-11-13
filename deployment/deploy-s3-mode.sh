#!/bin/bash

##########################################################################
# AWS Auto-Tagger S3 Mode Deployment Script
# Deploys Lambda function with S3 trigger for multi-region support
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
CLOUDTRAIL_BUCKET_NAME="auto-tagger-cloudtrail-logs"
LAMBDA_TIMEOUT=300  # 5 minutes for batch processing
LAMBDA_MEMORY=512   # More memory for S3 downloads

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}AWS Auto-Tagger S3 Mode Deployment${NC}"
echo -e "${BLUE}Multi-Region from Single Deployment${NC}"
echo -e "${BLUE}========================================${NC}"

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}

echo -e "${YELLOW}Account ID: ${ACCOUNT_ID}${NC}"
echo -e "${YELLOW}Deployment Region: ${REGION}${NC}"
echo -e "${YELLOW}CloudTrail: Will capture events from ALL regions${NC}"
echo -e ""

# Step 1: Create S3 Bucket for CloudTrail
echo -e "\n${YELLOW}[1/7] Creating S3 Bucket for CloudTrail...${NC}"

FULL_BUCKET_NAME="${CLOUDTRAIL_BUCKET_NAME}-${ACCOUNT_ID}"

if aws s3 ls "s3://${FULL_BUCKET_NAME}" 2>/dev/null; then
    echo -e "${GREEN}✓ S3 bucket already exists: ${FULL_BUCKET_NAME}${NC}"
else
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket ${FULL_BUCKET_NAME} --region ${REGION}
    else
        aws s3api create-bucket --bucket ${FULL_BUCKET_NAME} --region ${REGION} --create-bucket-configuration LocationConstraint=${REGION}
    fi
    echo -e "${GREEN}✓ S3 bucket created: ${FULL_BUCKET_NAME}${NC}"
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

echo -e "${GREEN}✓ S3 bucket policy configured${NC}"

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

echo -e "${GREEN}✓ Lambda role: ${ROLE_ARN}${NC}"

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

echo -e "${GREEN}✓ Policies attached${NC}"
echo -e "${YELLOW}Waiting for IAM role to be available...${NC}"
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
  s3_cloudtrail_processor.py \
  __init__.py > /dev/null 2>&1

ZIP_SIZE=$(ls -lh ${LAMBDA_ZIP} | awk '{print $5}')
echo -e "${GREEN}✓ Lambda packaged: ${LAMBDA_ZIP} (${ZIP_SIZE})${NC}"

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

echo -e "${GREEN}✓ Lambda deployed: ${LAMBDA_ARN}${NC}"

# Wait for Lambda to be active
echo -e "${YELLOW}Waiting for Lambda to be active...${NC}"
aws lambda wait function-active --function-name ${FUNCTION_NAME} --region ${REGION}

# Step 7: Configure S3 to trigger Lambda
echo -e "\n${YELLOW}[7/7] Configuring S3 Event Notification...${NC}"

# Add Lambda permission for S3
aws lambda add-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowS3Invoke \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn "arn:aws:s3:::${FULL_BUCKET_NAME}" \
  --region ${REGION} 2>/dev/null || echo -e "${YELLOW}(Permission may already exist)${NC}"

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

echo -e "${GREEN}✓ S3 event notification configured${NC}"

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
    echo -e "${GREEN}✓ CloudTrail trail: ${TRAIL_ARN}${NC}"
    
    # Start logging
    aws cloudtrail start-logging --name ${CLOUDTRAIL_NAME} --region ${REGION} 2>/dev/null || true
    echo -e "${GREEN}✓ CloudTrail logging started${NC}"
else
    echo -e "${YELLOW}⚠ CloudTrail not configured (may already exist with different name)${NC}"
fi

# Cleanup
rm -f /tmp/lambda-trust-policy.json
rm -f /tmp/lambda-s3-policy.json
rm -f /tmp/cloudtrail-bucket-policy.json
rm -f /tmp/s3-notification.json

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}✓ S3 Mode Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\n${BLUE}Architecture:${NC}"
echo -e "  ✓ ONE Lambda in ${REGION}"
echo -e "  ✓ Handles resources from ALL regions"
echo -e "  ✓ Triggered by S3 CloudTrail logs"
echo -e ""
echo -e "${YELLOW}Summary:${NC}"
echo -e "  Lambda Function: ${FUNCTION_NAME}"
echo -e "  Lambda ARN: ${LAMBDA_ARN}"
echo -e "  Trigger: S3 bucket events"
echo -e "  CloudTrail Bucket: ${FULL_BUCKET_NAME}"
echo -e "  CloudTrail: ${CLOUDTRAIL_NAME} (multi-region)"
echo -e "  Region: ${REGION}"
echo -e ""
echo -e "${YELLOW}How It Works:${NC}"
echo -e "  1. CloudTrail captures API calls from ALL regions"
echo -e "  2. Logs written to S3 bucket: ${FULL_BUCKET_NAME}"
echo -e "  3. S3 triggers Lambda on new log files"
echo -e "  4. Lambda tags resources in their respective regions"
echo -e ""
echo -e "${YELLOW}Test It:${NC}"
echo -e "  # Create EC2 in ANY region"
echo -e "  aws ec2 run-instances --image-id ami-xxx --instance-type t2.micro --region eu-west-1"
echo -e ""
echo -e "  # Wait ~5 minutes for CloudTrail logs"
echo -e "  # Then check Lambda logs:"
echo -e "  aws logs tail /aws/lambda/${FUNCTION_NAME} --follow --region ${REGION}"
echo -e ""
echo -e "${YELLOW}Monitor:${NC}"
echo -e "  aws logs tail /aws/lambda/${FUNCTION_NAME} --follow --region ${REGION}"
echo -e ""
echo -e "${GREEN}🎉 You can now create resources in ANY region and they'll be auto-tagged!${NC}"
echo -e ""

