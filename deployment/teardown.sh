#!/bin/bash

##########################################################################
# AWS Auto-Tagger Teardown Script
# Removes all resources created by the S3-mode deployment
##########################################################################

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FUNCTION_NAME="auto-tagger"
LAMBDA_ROLE_NAME="auto-tagger-lambda-role"
CLOUDTRAIL_NAME="auto-tagger-trail"

REGION=${AWS_REGION:-us-east-1}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo -e "${RED}AWS Auto-Tagger Teardown${NC}"
echo -e "${RED}========================================${NC}"

read -p "Delete Lambda function, IAM role, and CloudTrail? (yes/no): " confirmation
if [ "$confirmation" != "yes" ]; then
    echo "Cancelled."
    exit 0
fi

# Step 1: Remove Lambda permission for S3
echo -e "\n${YELLOW}[1/5] Removing Lambda S3 permission...${NC}"
aws lambda remove-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowS3Invoke \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

# Step 2: Delete Lambda function
echo -e "\n${YELLOW}[2/5] Deleting Lambda function...${NC}"
aws lambda delete-function \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

# Step 3: Delete IAM role and policies
echo -e "\n${YELLOW}[3/5] Deleting IAM role...${NC}"
aws iam delete-role-policy \
  --role-name ${LAMBDA_ROLE_NAME} \
  --policy-name auto-tagger-s3-permissions 2>/dev/null || true

aws iam delete-role \
  --role-name ${LAMBDA_ROLE_NAME} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

# Step 4: Stop CloudTrail
echo -e "\n${YELLOW}[4/5] Stopping CloudTrail...${NC}"
aws cloudtrail stop-logging \
  --name ${CLOUDTRAIL_NAME} \
  --region ${REGION} 2>/dev/null || true

aws cloudtrail delete-trail \
  --name ${CLOUDTRAIL_NAME} \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

# Step 5: Cleanup S3 bucket (optional - asks user)
echo -e "\n${YELLOW}[5/5] S3 Bucket cleanup...${NC}"
echo -e "${YELLOW}Note: S3 buckets with CloudTrail logs are not automatically deleted.${NC}"
read -p "Delete S3 bucket and all CloudTrail logs? (yes/no): " delete_bucket

if [ "$delete_bucket" = "yes" ]; then
    BUCKET_NAME=$(aws s3 ls | grep "auto-tagger-cloudtrail-logs.*${ACCOUNT_ID}" | awk '{print $3}' | head -n 1)
    if [ ! -z "$BUCKET_NAME" ]; then
        echo -e "${YELLOW}Deleting bucket: ${BUCKET_NAME}${NC}"
        aws s3 rb s3://${BUCKET_NAME} --force --region ${REGION} 2>/dev/null || true
        echo -e "${GREEN}✓ Bucket deleted${NC}"
    else
        echo -e "${YELLOW}No bucket found${NC}"
    fi
else
    echo -e "${YELLOW}Skipping S3 bucket deletion${NC}"
fi

rm -f ../lambda_function.zip 2>/dev/null || true

echo -e "\n${GREEN}Teardown complete${NC}"

