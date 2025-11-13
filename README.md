# AWS Auto-Tagger: Automatic Resource Tagging by Creator ARN

**Automatically tags AWS resources with the user ARN who created them using CloudTrail, S3, and Lambda.**

## 🎯 Problem Statement

Organizations struggle with:
- ❌ Cost allocation - Who's spending what?
- ❌ Compliance tracking - Who created each resource?
- ❌ Resource ownership - Which team owns what?
- ❌ Manual tagging - Error-prone and doesn't scale

## ✅ Solution

Serverless auto-tagging via CloudTrail + S3 + Lambda:
- ✅ **Multi-region support** - ONE Lambda handles ALL regions
- ✅ **Automatic tagging** - No manual intervention required
- ✅ **Audit trail** - Full logging in CloudWatch
- ✅ **7+ AWS services** - EC2, S3, RDS, Lambda, DynamoDB, SNS, SQS

## 🚀 Quick Start

### 1. Deploy the Solution 🌍

**ONE Lambda in ONE region handles ALL regions!**

```bash
cd deployment

# ONE deployment for ALL regions!
export AWS_REGION=us-east-1
./deploy.sh
```

### 2. Test It

```bash
# Create EC2 instance in ANY region
aws ec2 run-instances --image-id ami-0c55b159cbfafe1f0 --instance-type t3.micro --region us-west-2

# Wait 5-10 minutes for CloudTrail logs to be delivered
# Then check tags
aws ec2 describe-tags --filters "Name=resource-id,Values=i-xxxxx" --region us-west-2

# You'll see tags: CreatedBy, CreatedDate, ManagedBy, etc.
```

## 📊 Features

| Feature | Details |
|---------|---------|
| **Supported Services** | EC2, S3, RDS, Lambda, DynamoDB, SNS, SQS |
| **Response Time** | Tagged within 5-10 minutes (CloudTrail delay) |
| **Throughput** | Batch processing of multiple resources |
| **Cost** | ~$3-5/month for typical org |
| **Scalability** | Serverless - auto-scales with Lambda |
| **Multi-Region** | ✅ ONE Lambda handles ALL regions |

## 🏗️ Architecture

```
CloudTrail (multi-region logs)
    ↓
S3 Bucket (log files)
    ↓
S3 Event Notification
    ↓
Lambda Function (parses + tags resources in all regions)
    ↓
CloudWatch (audit trail)
```

**Key Benefit**: ONE Lambda in ONE region can tag resources in ALL regions!

## 📁 Project Structure

```
.
├── README.md                         ← This file
├── ARCHITECTURE.md                   ← Technical architecture details
├── lambda_function/
│   ├── lambda_handler.py             ← Main Lambda function
│   ├── cloudtrail_parser.py          ← CloudTrail event parsing
│   ├── tag_manager.py                ← Multi-service tagging logic
│   ├── s3_cloudtrail_processor.py    ← S3 log processing
│   └── requirements.txt              ← Lambda dependencies
├── deployment/
│   ├── deploy.sh                     ← Automated deployment script
│   └── teardown.sh                   ← Cleanup script
├── tests/
│   ├── test_cloudtrail_parser.py     ← Unit tests
│   └── mock_events.json              ← Test event data
└── requirements.txt                  ← Development dependencies
```

## ✨ Tags Applied

Every resource gets automatically tagged with:

```json
{
  "CreatedBy": "arn:aws:iam::account:user/john.doe",
  "CreatedDate": "2024-01-15T10:30:00Z",
  "ManagedBy": "auto-tagger",
  "Environment": "production",
  "SourceIP": "192.0.2.1",
  "AccountId": "123456789012"
}
```

## 🧹 Cleanup

Delete all resources:

```bash
cd deployment
bash teardown.sh
# Confirm with "yes" twice
```

## 📈 Scalability

- **Multi-Region**: ONE Lambda handles ALL regions automatically
- **Batch Processing**: Processes multiple resources from each CloudTrail log file
- **High Volume**: Lambda configured with 512MB memory and 5-minute timeout
- **Cost Savings**: Single Lambda deployment reduces operational costs

## 📚 Documentation

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Detailed technical architecture and design decisions

## 🔗 AWS Services Used

- **AWS Lambda** - Serverless compute for tagging logic
- **AWS CloudTrail** - API call logging across all regions
- **Amazon S3** - CloudTrail log storage
- **AWS IAM** - Permission management
- **Amazon CloudWatch** - Logging and monitoring

## 📊 Performance Metrics

| Metric | Value |
|--------|-------|
| Cold Start | 2-5 seconds |
| Warm Start | 100-500ms |
| CloudTrail Delay | 5-10 minutes |
| Batch Processing | Multiple resources per log file |
| Monthly Cost (100K resources) | $3-5 |

---

**Version**: 1.0
