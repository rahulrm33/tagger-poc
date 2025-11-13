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

echo -e "${RED}Auto-Tagger Teardown${NC}"
read -p "Delete all resources? (yes/no): " confirmation
[ "$confirmation" != "yes" ] && echo "Cancelled." && exit 0

echo -e "\n${YELLOW}[1/5] Lambda Permission...${NC}"
aws lambda remove-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowS3Invoke \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

echo -e "${YELLOW}[2/5] Lambda Function...${NC}"
aws lambda delete-function \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

echo -e "${YELLOW}[3/5] IAM Role...${NC}"
aws iam delete-role-policy \
  --role-name ${LAMBDA_ROLE_NAME} \
  --policy-name auto-tagger-s3-permissions 2>/dev/null || true

aws iam delete-role \
  --role-name ${LAMBDA_ROLE_NAME} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

echo -e "${YELLOW}[4/5] CloudTrail...${NC}"
aws cloudtrail stop-logging \
  --name ${CLOUDTRAIL_NAME} \
  --region ${REGION} 2>/dev/null || true

aws cloudtrail delete-trail \
  --name ${CLOUDTRAIL_NAME} \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Done${NC}"

echo -e "${YELLOW}[5/5] S3 Bucket (optional)...${NC}"
read -p "Delete S3 bucket and logs? (yes/no): " delete_bucket

if [ "$delete_bucket" = "yes" ]; then
    BUCKET_NAME=$(aws s3 ls | grep "auto-tagger-cloudtrail-logs.*${ACCOUNT_ID}" | awk '{print $3}' | head -n 1)
    [ ! -z "$BUCKET_NAME" ] && aws s3 rb s3://${BUCKET_NAME} --force --region ${REGION} 2>/dev/null || true
    echo -e "${GREEN}✓ Done${NC}"
else
    echo -e "${YELLOW}✓ Skipped${NC}"
fi

rm -f ../lambda_function.zip 2>/dev/null || true
echo -e "\n${GREEN}✓ Teardown complete${NC}"

