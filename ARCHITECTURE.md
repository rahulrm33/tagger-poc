# AWS Auto-Tagger: System Architecture

Comprehensive technical architecture documentation for the auto-tagging solution.

## System Overview

The AWS Auto-Tagger is an event-driven, serverless solution that automatically applies creator attribution tags to AWS resources.

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     AWS Account (Multi-Region)                  │
│                                                                 │
│  ┌──────────────────┐                                           │
│  │   CloudTrail     │  (Captures events from ALL regions)       │
│  │  (Multi-Region)  │                                           │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           │ (Log files .json.gz)                                │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │   S3 Bucket      │                                           │
│  │ (CloudTrail Logs)│                                           │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           │ (S3 Event Notification)                             │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │   Lambda         │                                           │
│  │   Function       │                                           │
│  │  (auto-tagger)   │                                           │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │  Tag Manager     │                                           │
│  │  (Multi-service  │                                           │
│  │   Multi-region)  │                                           │
│  └────────┬─────────┘                                           │
│           │                                                     │
│    ┌──────┼──────┬───────────┬───────────┐                     │
│    ▼      ▼      ▼           ▼           ▼                     │
│  ┌────┐ ┌────┐ ┌─────┐   ┌──────┐   ┌──────┐                  │
│  │EC2 │ │S3  │ │RDS  │   │Lambda│   │ SNS  │  (+ others)      │
│  └────┘ └────┘ └─────┘   └──────┘   └──────┘                  │
│    │      │      │           │           │                     │
│    └──────┴──────┴───────────┴───────────┘                     │
│                   │                                             │
│                   ▼                                             │
│  ┌────────────────────────────┐                                │
│  │  CloudWatch Logs (Audit)   │                                │
│  └────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. CloudTrail

**Purpose**: Captures all API calls to AWS services across all regions

**Configuration**:
- Multi-region trail enabled
- Logs written to S3 bucket in gzip-compressed JSON format
- Log file validation enabled for integrity
- Captures management events (resource creation, modification, deletion)

**Events Monitored**:
- `ec2:RunInstances`
- `ec2:CreateVolume`
- `ec2:CreateSnapshot`
- `ec2:CreateSecurityGroup`
- `s3:CreateBucket`
- `rds:CreateDBInstance`
- `rds:CreateDBCluster`
- `lambda:CreateFunction`
- `dynamodb:CreateTable`
- `sns:CreateTopic`
- `sqs:CreateQueue`

**Log Delivery**:
- CloudTrail delivers log files to S3 within 5-15 minutes
- Log file format: `AWSLogs/{AccountId}/CloudTrail/{Region}/{Year}/{Month}/{Day}/*.json.gz`

### 2. S3 Bucket (CloudTrail Logs)

**Purpose**: Stores CloudTrail log files and triggers Lambda function

**Configuration**:
- Bucket policy allows CloudTrail to write logs
- S3 event notification configured for `s3:ObjectCreated:*`
- Event filter: Suffix `.json.gz` (CloudTrail log files only)
- Triggers Lambda function when new log file is created

**Event Notification**:
```json
{
  "LambdaFunctionConfigurations": [{
    "Events": ["s3:ObjectCreated:*"],
    "LambdaFunctionArn": "arn:aws:lambda:region:account:function:auto-tagger",
    "Filter": {
      "Key": {
        "FilterRules": [{"Name": "suffix", "Value": ".json.gz"}]
      }
    }
  }]
}
```

### 3. Lambda Function (auto-tagger)

**Purpose**: Process events and apply tags to resources

**Runtime**: Python 3.11

**Memory**: 512 MB (for S3 log processing)

**Timeout**: 300 seconds (5 minutes for batch processing)

**Environment Variables**:
- `AWS_REGION`: Deployment region
- `ENVIRONMENT`: Environment tag value (default: production)
- `TRIGGER_MODE`: Set to `s3` for S3-triggered mode

**Trigger**: S3 event notification when CloudTrail log file is created

**Modules**:

#### `s3_cloudtrail_processor.py`
- Downloads CloudTrail log files from S3
- Decompresses gzip files
- Extracts CloudTrail records
- Filters for resource creation events
- Converts to standardized format

#### `cloudtrail_parser.py`
- Parses individual CloudTrail events
- Extracts user ARN and resource information
- Validates event format
- Maps events to resource IDs
- Supports multiple AWS services

#### `tag_manager.py`
- Manages tagging for 7+ AWS services
- Handles service-specific tagging APIs
- Multi-region resource tagging
- Error tracking and logging
- Batch processing support

#### `lambda_handler.py`
- Main entry point for S3 events
- Orchestrates S3 log processing
- Batch processes multiple CloudTrail events
- Error handling and retry logic
- Response formatting with metrics

### Backup and Recovery

1. **Configuration Backup**
   - Export Lambda code: `aws lambda get-function`
   - Export S3 notification config: `aws s3api get-bucket-notification-configuration`
   - Export IAM policies: `aws iam get-role-policy`

2. **Data Recovery**
   - CloudTrail log files persist in S3
   - Can reprocess old log files by re-invoking Lambda
   - CloudWatch logs retained for 7 days (configurable)
   - S3 lifecycle policies for long-term log archival

3. **Recovery Procedures**
   - Redeploy via deploy.sh script
   - Reprocess specific log files: Manually invoke Lambda with S3 event
   - Bulk reprocessing: Use S3 batch operations to re-trigger Lambda

### Monitoring and Alerting

```bash
# Lambda invocation count
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum

# Lambda errors
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-02T00:00:00Z \
  --period 3600 \
  --statistics Sum
```

## Key Benefits

### Multi-Region Architecture
- ✅ **ONE Lambda** in ONE region handles resources in ALL regions
- ✅ **Simplified deployment** - No need to deploy to each region
- ✅ **Cost efficient** - Single function vs multiple regional functions
- ✅ **Easy maintenance** - Update code in one place

### Trade-offs
- ⏱️ **Tagging delay**: 5-15 minutes (CloudTrail log delivery time)
- 🌍 **Cross-region API calls**: Lambda in us-east-1 can tag EC2 in eu-west-1

## Future Enhancements

1. **Cross-Account Tagging**: Tag resources in other AWS accounts (via assume role)
2. **Custom Tagging Logic**: Organization-specific tagging rules
3. **Integration with CMDB**: Export tags to inventory system
4. **Advanced Analytics**: Query tags across all resources
5. **Cost Allocation**: Use tags for cost center allocation
6. **Notification System**: Alert on tagging failures via SNS

---
