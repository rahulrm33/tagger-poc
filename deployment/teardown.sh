#!/bin/bash

##########################################################################
# AWS Auto-Tagger Teardown Script
# Removes all resources created by the deployment script
##########################################################################

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
FUNCTION_NAME="auto-tagger"
LAMBDA_ROLE_NAME="auto-tagger-lambda-role"
EVENTBRIDGE_ROLE_NAME="auto-tagger-eventbridge-role"
DEAD_LETTER_QUEUE_NAME="auto-tagger-dlq"
RULE_NAME="auto-tagger-rule"

REGION=${AWS_REGION:-us-east-1}

echo -e "${RED}========================================${NC}"
echo -e "${RED}AWS Auto-Tagger Teardown${NC}"
echo -e "${RED}========================================${NC}"

# Confirmation
read -p "Are you sure you want to delete all auto-tagger resources? (yes/no): " confirmation

if [ "$confirmation" != "yes" ]; then
    echo -e "${YELLOW}Teardown cancelled.${NC}"
    exit 0
fi

echo -e "\n${YELLOW}This will delete:${NC}"
echo -e "  - Lambda function: ${FUNCTION_NAME}"
echo -e "  - IAM roles: ${LAMBDA_ROLE_NAME}, ${EVENTBRIDGE_ROLE_NAME}"
echo -e "  - EventBridge rule: ${RULE_NAME}"
echo -e "  - SQS queue: ${DEAD_LETTER_QUEUE_NAME}"

read -p "Continue? (yes/no): " confirm
if [ "$confirm" != "yes" ]; then
    echo -e "${YELLOW}Teardown cancelled.${NC}"
    exit 0
fi

# Step 1: Remove EventBridge targets
echo -e "\n${YELLOW}[1/5] Removing EventBridge targets...${NC}"
aws events remove-targets \
  --rule ${RULE_NAME} \
  --region ${REGION} \
  --ids "1" 2>/dev/null || true
echo -e "${GREEN}✓ EventBridge targets removed${NC}"

# Step 2: Delete EventBridge rule
echo -e "\n${YELLOW}[2/5] Deleting EventBridge rule...${NC}"
aws events delete-rule \
  --name ${RULE_NAME} \
  --force \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ EventBridge rule deleted${NC}"

# Step 3: Delete Lambda function
echo -e "\n${YELLOW}[3/5] Deleting Lambda function...${NC}"
aws lambda delete-function \
  --function-name ${FUNCTION_NAME} \
  --region ${REGION} 2>/dev/null || true
echo -e "${GREEN}✓ Lambda function deleted${NC}"

# Step 4: Delete IAM roles and policies
echo -e "\n${YELLOW}[4/5] Deleting IAM roles and policies...${NC}"

# Delete inline policies from Lambda role
aws iam delete-role-policy \
  --role-name ${LAMBDA_ROLE_NAME} \
  --policy-name auto-tagger-permissions 2>/dev/null || true

# Delete Lambda role
aws iam delete-role \
  --role-name ${LAMBDA_ROLE_NAME} 2>/dev/null || true

# Delete inline policies from EventBridge role
aws iam delete-role-policy \
  --role-name ${EVENTBRIDGE_ROLE_NAME} \
  --policy-name eventbridge-lambda-invoke 2>/dev/null || true

# Delete EventBridge role
aws iam delete-role \
  --role-name ${EVENTBRIDGE_ROLE_NAME} 2>/dev/null || true

echo -e "${GREEN}✓ IAM roles and policies deleted${NC}"

# Step 5: Delete SQS Dead Letter Queue
echo -e "\n${YELLOW}[5/5] Deleting SQS Dead Letter Queue...${NC}"

DLQ_URL=$(aws sqs get-queue-url \
  --queue-name ${DEAD_LETTER_QUEUE_NAME} \
  --region ${REGION} \
  --query 'QueueUrl' \
  --output text 2>/dev/null || echo "")

if [ ! -z "$DLQ_URL" ]; then
  aws sqs delete-queue \
    --queue-url ${DLQ_URL} \
    --region ${REGION} 2>/dev/null || true
fi

echo -e "${GREEN}✓ SQS queue deleted${NC}"

# Cleanup
rm -f ../lambda_function.zip

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Teardown Completed! ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\n${YELLOW}All auto-tagger resources have been removed.${NC}"

