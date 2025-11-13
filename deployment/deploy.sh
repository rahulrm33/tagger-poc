#!/bin/bash

##########################################################################
# AWS Auto-Tagger Deployment Script
# Deploys Lambda function, EventBridge rules, and IAM roles
##########################################################################

set -e

# Get script directory for relative path resolution
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

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
LAMBDA_TIMEOUT=60
LAMBDA_MEMORY=256

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}AWS Auto-Tagger Deployment${NC}"
echo -e "${GREEN}========================================${NC}"

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=${AWS_REGION:-us-east-1}

echo -e "${YELLOW}Account ID: ${ACCOUNT_ID}${NC}"
echo -e "${YELLOW}Region: ${REGION}${NC}"

# Step 1: Create SQS Dead Letter Queue
echo -e "\n${YELLOW}[1/6] Creating Dead Letter Queue...${NC}"
DLQ_URL=$(aws sqs create-queue \
  --queue-name ${DEAD_LETTER_QUEUE_NAME} \
  --region ${REGION} \
  --query 'QueueUrl' \
  --output text 2>/dev/null || echo "queue-exists")

if [ "$DLQ_URL" != "queue-exists" ]; then
  echo -e "${GREEN}✓ Dead Letter Queue created: ${DLQ_URL}${NC}"
else
  DLQ_URL=$(aws sqs get-queue-url \
    --queue-name ${DEAD_LETTER_QUEUE_NAME} \
    --region ${REGION} \
    --query 'QueueUrl' \
    --output text)
  echo -e "${GREEN}✓ Dead Letter Queue exists: ${DLQ_URL}${NC}"
fi

# Step 2: Create Lambda Execution Role
echo -e "\n${YELLOW}[2/6] Creating Lambda Execution Role...${NC}"

# Create trust policy
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

# Create role if it doesn't exist
ROLE_ARN=$(aws iam create-role \
  --role-name ${LAMBDA_ROLE_NAME} \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
  --query 'Role.Arn' \
  --output text 2>/dev/null || \
  aws iam get-role \
    --role-name ${LAMBDA_ROLE_NAME} \
    --query 'Role.Arn' \
    --output text)

echo -e "${GREEN}✓ Lambda role created/retrieved: ${ROLE_ARN}${NC}"

# Step 3: Attach Policies to Lambda Role
echo -e "\n${YELLOW}[3/6] Attaching IAM Policies to Lambda Role...${NC}"

# Create inline policy from the policy file
POLICY_FILE="${PROJECT_ROOT}/iam/lambda_policy.json"
aws iam put-role-policy \
  --role-name ${LAMBDA_ROLE_NAME} \
  --policy-name auto-tagger-permissions \
  --policy-document file://${POLICY_FILE}

echo -e "${GREEN}✓ Policies attached to Lambda role${NC}"

# Wait for role to be available
echo -e "${YELLOW}Waiting for IAM role to be available...${NC}"
sleep 5

# Step 4: Package Lambda Function
echo -e "\n${YELLOW}[4/6] Packaging Lambda Function...${NC}"

LAMBDA_DIR="${PROJECT_ROOT}/lambda_function"
LAMBDA_ZIP="${PROJECT_ROOT}/lambda_function.zip"

# Create deployment package - LEAN VERSION (no dependencies)
# AWS Lambda includes boto3, botocore, requests, urllib3 pre-installed
# so we only need to zip our source code
rm -f ${LAMBDA_ZIP}

cd ${LAMBDA_DIR}
zip -j ${LAMBDA_ZIP} \
  lambda_handler.py \
  cloudtrail_parser.py \
  tag_manager.py \
  __init__.py > /dev/null 2>&1

# Get zip file size
ZIP_SIZE=$(ls -lh ${LAMBDA_ZIP} | awk '{print $5}')
echo -e "${GREEN}✓ Lambda function packaged: ${LAMBDA_ZIP} (${ZIP_SIZE})${NC}"

cd ${SCRIPT_DIR}

# Step 5: Create or Update Lambda Function
echo -e "\n${YELLOW}[5/6] Creating/Updating Lambda Function...${NC}"

LAMBDA_ARN=$(aws lambda create-function \
  --function-name ${FUNCTION_NAME} \
  --runtime python3.11 \
  --role ${ROLE_ARN} \
  --handler lambda_handler.lambda_handler \
  --zip-file fileb://${LAMBDA_ZIP} \
  --timeout ${LAMBDA_TIMEOUT} \
  --memory-size ${LAMBDA_MEMORY} \
  --environment Variables='{ENVIRONMENT=production}' \
  --region ${REGION} \
  --query 'FunctionArn' \
  --output text 2>/dev/null || \
  aws lambda update-function-code \
    --function-name ${FUNCTION_NAME} \
    --zip-file fileb://${LAMBDA_ZIP} \
    --region ${REGION} \
    --query 'FunctionArn' \
    --output text)

echo -e "${GREEN}✓ Lambda function deployed: ${LAMBDA_ARN}${NC}"

# Step 6: Create EventBridge Rule
echo -e "\n${YELLOW}[6/6] Creating EventBridge Rule...${NC}"

# Create EventBridge role
cat > /tmp/eventbridge-trust-policy.json << 'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "events.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

EVENTBRIDGE_ROLE_ARN=$(aws iam create-role \
  --role-name ${EVENTBRIDGE_ROLE_NAME} \
  --assume-role-policy-document file:///tmp/eventbridge-trust-policy.json \
  --query 'Role.Arn' \
  --output text 2>/dev/null || \
  aws iam get-role \
    --role-name ${EVENTBRIDGE_ROLE_NAME} \
    --query 'Role.Arn' \
    --output text)

# Create EventBridge role policy
cat > /tmp/eventbridge-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "lambda:InvokeFunction",
      "Resource": "${LAMBDA_ARN}"
    },
    {
      "Effect": "Allow",
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:${REGION}:${ACCOUNT_ID}:${DEAD_LETTER_QUEUE_NAME}"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name ${EVENTBRIDGE_ROLE_NAME} \
  --policy-name eventbridge-lambda-invoke \
  --policy-document file:///tmp/eventbridge-policy.json 2>/dev/null || true

sleep 3

# Get DLQ ARN
DLQ_ARN=$(aws sqs get-queue-attributes \
  --queue-url ${DLQ_URL} \
  --attribute-names QueueArn \
  --region ${REGION} \
  --query 'Attributes.QueueArn' \
  --output text)

# Create or update EventBridge rule
RULE_NAME="auto-tagger-rule"

aws events put-rule \
  --name ${RULE_NAME} \
  --event-bus-name default \
  --state ENABLED \
  --region ${REGION} \
  --event-pattern '{
    "source": ["aws.ec2", "aws.s3", "aws.rds", "aws.lambda", "aws.dynamodb", "aws.sns", "aws.sqs"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
      "eventName": [
        "RunInstances",
        "CreateVolume",
        "CreateSnapshot",
        "CreateSecurityGroup",
        "CreateBucket",
        "CreateDBInstance",
        "CreateDBCluster",
        "CreateFunction",
        "CreateTable",
        "CreateTopic",
        "CreateQueue"
      ]
    }
  }'

echo -e "${GREEN}✓ EventBridge rule created: ${RULE_NAME}${NC}"

# Wait for EventBridge role policy to propagate
echo -e "${YELLOW}Waiting for EventBridge role policy to propagate...${NC}"
sleep 5

# Add Lambda as target (put-targets creates or updates)
echo -e "${YELLOW}Adding Lambda as target to EventBridge rule...${NC}"

# Create targets JSON file to avoid quote escaping issues
cat > /tmp/eventbridge-targets.json << TARGETS_EOF
[
  {
    "Id": "1",
    "Arn": "${LAMBDA_ARN}",
    "RoleArn": "${EVENTBRIDGE_ROLE_ARN}",
    "DeadLetterConfig": {
      "Arn": "${DLQ_ARN}"
    }
  }
]
TARGETS_EOF

if aws events put-targets \
  --rule ${RULE_NAME} \
  --region ${REGION} \
  --targets file:///tmp/eventbridge-targets.json 2>&1; then
  echo -e "${GREEN}✓ Lambda added to EventBridge rule targets${NC}"
else
  echo -e "${RED}✗ Failed to add Lambda to EventBridge targets${NC}"
  exit 1
fi

# Add Lambda permission for EventBridge
echo -e "${YELLOW}Adding Lambda invoke permission for EventBridge...${NC}"
if aws lambda add-permission \
  --function-name ${FUNCTION_NAME} \
  --statement-id AllowEventBridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
  --region ${REGION} 2>&1; then
  echo -e "${GREEN}✓ Lambda permission added for EventBridge${NC}"
else
  echo -e "${YELLOW}(Lambda permission may already exist - that's okay)${NC}"
fi

# Verify targets were created
echo -e "${YELLOW}Verifying EventBridge targets...${NC}"
TARGET_COUNT=$(aws events list-targets-by-rule \
  --rule ${RULE_NAME} \
  --region ${REGION} \
  --query 'length(Targets)' \
  --output text)

if [ "$TARGET_COUNT" -gt 0 ]; then
  echo -e "${GREEN}✓ EventBridge targets verified: ${TARGET_COUNT} target(s) found${NC}"
else
  echo -e "${RED}✗ ERROR: No targets found for EventBridge rule!${NC}"
  echo -e "${RED}   This means Lambda will NOT be invoked.${NC}"
  echo -e "${RED}   Please run the following to add targets manually:${NC}"
  echo -e "${RED}   aws events put-targets \\${NC}"
  echo -e "${RED}     --rule ${RULE_NAME} \\${NC}"
  echo -e "${RED}     --region ${REGION} \\${NC}"
  echo -e "${RED}     --targets \"Id\"=\"1\",\"Arn\"=\"${LAMBDA_ARN}\",\"RoleArn\"=\"${EVENTBRIDGE_ROLE_ARN}\",\"DeadLetterConfig\"=\"{\\\"Arn\\\":\\\"${DLQ_ARN}\\\"}\"${NC}"
  exit 1
fi

# Cleanup
rm -f /tmp/lambda-trust-policy.json
rm -f /tmp/eventbridge-trust-policy.json
rm -f /tmp/eventbridge-policy.json
rm -f /tmp/eventbridge-targets.json

echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Completed Successfully! ✓${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "\n${YELLOW}Summary:${NC}"
echo -e "  Function Name: ${FUNCTION_NAME}"
echo -e "  Lambda ARN: ${LAMBDA_ARN}"
echo -e "  Lambda Role: ${ROLE_ARN}"
echo -e "  EventBridge Rule: ${RULE_NAME}"
echo -e "  Dead Letter Queue: ${DLQ_URL}"
echo -e "  Region: ${REGION}"
echo -e "\n${YELLOW}Next Steps:${NC}"
echo -e "  1. Enable CloudTrail in your AWS account"
echo -e "  2. Verify the Lambda function is working by checking CloudWatch logs"
echo -e "  3. Create a test resource and verify it gets tagged"
echo -e "\n${YELLOW}Monitor Logs:${NC}"
echo -e "  aws logs tail /aws/lambda/${FUNCTION_NAME} --follow"

