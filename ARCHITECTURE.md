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

### 4. IAM Roles and Policies

#### Lambda Execution Role
- Principal: Lambda service
- Permissions:
  - **CloudWatch Logs**: Create log groups/streams, write logs
  - **S3**: Read CloudTrail log files (`s3:GetObject`, `s3:ListBucket`)
  - **EC2**: Create tags on instances, volumes, snapshots, security groups
  - **S3**: Put bucket tagging
  - **RDS**: Add tags to DB instances/clusters
  - **Lambda**: Tag functions
  - **DynamoDB**: Tag tables
  - **SNS**: Tag topics
  - **SQS**: Tag queues
  - **Multi-Region**: Permissions apply to ALL AWS regions

#### S3 Bucket Policy
- Allows CloudTrail service to write log files
- Allows Lambda to read log files
- Principal: CloudTrail service, Lambda execution role

## Data Flow

### Event Processing Flow

```
1. Resource Creation (ANY AWS region)
   └─> API Call (e.g., RunInstances in eu-west-1)

2. CloudTrail Logging
   └─> Event recorded
   └─> Log file written to S3 (5-15 minute delay)

3. S3 Event Notification
   └─> New .json.gz file created
   └─> S3 triggers Lambda function

4. S3CloudTrailProcessor.process_s3_event()
   ├─> Download log file from S3
   ├─> Decompress gzip file
   ├─> Parse JSON records
   ├─> Filter for creation events
   └─> Return list of CloudTrail events

5. For each CloudTrail event:
   CloudTrailParser.parse_event()
   ├─> Extract user ARN
   ├─> Extract event name
   ├─> Extract resource region
   ├─> Validate event
   └─> Extract resource IDs

6. TagManager.tag_resource()
   ├─> Identify service (EC2, S3, RDS, etc.)
   ├─> Identify resource region
   ├─> Build tags (CreatedBy, CreatedDate, etc.)
   ├─> Create/reuse boto3 client for target region
   ├─> Call service-specific tagging API
   └─> Handle errors

7. Response Generation
   ├─> Total events processed
   ├─> Total resources tagged
   ├─> Failed resources list
   └─> Per-event results

8. CloudWatch Logging
   └─> All actions logged with metrics
```

### Example Event Flow: EC2 Instance Creation

```json
{
  "detail": {
    "eventName": "RunInstances",
    "userIdentity": {
      "arn": "arn:aws:iam::123456789012:user/alice"
    },
    "requestParameters": {
      "instancesSet": {
        "items": [
          {"instanceId": "i-0123456789abcdef0"}
        ]
      }
    },
    "eventTime": "2024-01-15T10:30:00Z"
  }
}
```

**Processing Steps**:

1. **Parse**: Extract user ARN and instance ID
2. **Validate**: Confirm event is supported
3. **Tag**: Apply tags to instance
   - `CreatedBy`: arn:aws:iam::123456789012:user/alice
   - `CreatedDate`: 2024-01-15T10:30:00Z
   - `ManagedBy`: auto-tagger
4. **Log**: Record action to CloudWatch
5. **Return**: Success response

### Resource Tagging Details

#### Tags Applied

All resources receive these tags:

```
CreatedBy: {user_arn}
CreatedDate: {iso_timestamp}
ManagedBy: auto-tagger
```

Additional tags (configurable):
- `Environment`: From environment variable
- `SourceIP`: From CloudTrail event
- `AccountId`: From user identity

## Service Integration

### Supported Services

| Service | Event | Resource Type |
|---------|-------|---------------|
| EC2 | RunInstances | instance |
| EC2 | CreateVolume | volume |
| EC2 | CreateSnapshot | snapshot |
| EC2 | CreateSecurityGroup | security-group |
| S3 | CreateBucket | bucket |
| RDS | CreateDBInstance | db |
| RDS | CreateDBCluster | cluster |
| Lambda | CreateFunction | function |
| DynamoDB | CreateTable | table |
| SNS | CreateTopic | topic |
| SQS | CreateQueue | queue |

### API Integration Patterns

#### EC2 (Create Tags)
```python
ec2_client.create_tags(
    Resources=['i-12345'],
    Tags=[{'Key': 'CreatedBy', 'Value': 'arn:aws:iam::...'}]
)
```

#### S3 (Put Bucket Tagging)
```python
s3_client.put_bucket_tagging(
    Bucket='my-bucket',
    Tagging={'TagSet': [{'Key': 'CreatedBy', 'Value': 'arn:aws:iam::...'}]}
)
```

#### RDS (Add Tags to Resource)
```python
rds_client.add_tags_to_resource(
    ResourceName='arn:aws:rds:region:account:db:dbname',
    Tags=[{'Key': 'CreatedBy', 'Value': 'arn:aws:iam::...'}]
)
```

## Scalability Considerations

### Throughput

- **Lambda Concurrency**: 1,000 concurrent executions (AWS default)
- **Batch Processing**: Multiple CloudTrail events processed per log file
- **Multi-Region**: Single Lambda handles resources in ALL regions
- **Processing Delay**: 5-15 minutes (CloudTrail log delivery time)

### Performance Optimizations

1. **Batch Processing**: Process all events in a CloudTrail log file at once
2. **Client Reuse**: Boto3 clients cached and reused for multiple resources
3. **Multi-Region Efficiency**: No need to deploy Lambda to each region
4. **Connection Pooling**: Boto3 manages HTTP connections
5. **Memory Allocation**: 512MB for faster S3 downloads and processing

### Cost Optimization

**Estimated Monthly Cost (for 100K resource creations)**:
1. **Lambda**: ~$3-5
   - Invocations: Based on CloudTrail log files created (~1K-5K/month)
   - Duration: 512MB @ 5-10 seconds average
2. **CloudTrail**: ~$2.00 per 100,000 events
3. **S3 Storage**: ~$0.50 (log files, compressed)
4. **Data Transfer**: Minimal (within AWS)

**Total**: ~$5-8/month for typical workload

**Recommendations**:
   - Single Lambda deployment (vs multiple per region)
   - CloudTrail log lifecycle policies (archive to Glacier after 30 days)
   - Monitor Lambda duration and optimize if needed

## Error Handling

### Error Categories

1. **Permission Denied**
   - Lambda role lacks tagging permissions
   - Resource doesn't support tagging
   - Action: Check IAM policy

2. **Resource Not Found**
   - Resource deleted before tagging
   - Resource in different region
   - Action: Log and continue

3. **Timeout**
   - API call takes too long
   - Network issues
   - Action: Retry or send to DLQ

4. **Invalid Event**
   - Malformed CloudTrail event
   - Missing required fields
   - Action: Log to CloudWatch

### Error Recovery

1. **Automatic Retry** (via Lambda)
   - Lambda retries failed S3 event notifications (up to 2 times)
   - CloudTrail logs persist in S3 for reprocessing
   - Can manually re-invoke Lambda with specific log file

2. **Failed Resource Tracking**
   - Each Lambda invocation tracks failed resources
   - Failures logged to CloudWatch with resource IDs
   - Can be extracted and retried manually

3. **Logging**
   - All errors logged to CloudWatch Logs
   - Structured logging with resource IDs, error codes
   - CloudWatch metrics for monitoring
   - Log retention: 7 days (configurable)

## Security Architecture

### Defense in Depth

1. **Access Control**
   - IAM roles with least privilege
   - Resource-based policies
   - Service control policies (optional)

2. **Data Protection**
   - CloudTrail encryption (at rest)
   - TLS for API calls (in transit)
   - Encryption keys managed by AWS

3. **Audit Trail**
   - CloudTrail logs all API calls
   - Lambda logs all tagging operations
   - CloudWatch metrics for monitoring

4. **Compliance**
   - HIPAA eligible
   - PCI DSS compliant
   - SOC 2 Type II certification

## Disaster Recovery

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
- 📦 **Batch processing**: Tags multiple resources per log file
- 🌍 **Cross-region API calls**: Lambda in us-east-1 can tag EC2 in eu-west-1

## Future Enhancements

1. **Cross-Account Tagging**: Tag resources in other AWS accounts (via assume role)
2. **Custom Tagging Logic**: Organization-specific tagging rules
3. **Integration with CMDB**: Export tags to inventory system
4. **Advanced Analytics**: Query tags across all resources
5. **Cost Allocation**: Use tags for cost center allocation
6. **Notification System**: Alert on tagging failures via SNS

---

**Architecture Version**: 1.0
**Last Updated**: November 2024

