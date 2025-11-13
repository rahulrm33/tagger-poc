"""
Unit tests for CloudTrail Parser
"""

import json
import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lambda_function'))

from cloudtrail_parser import CloudTrailParser


class TestCloudTrailParser(unittest.TestCase):
    """Test CloudTrailParser functionality"""

    def test_parse_run_instances_event(self):
        """Test parsing EC2 RunInstances event"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/test-user"
                },
                "requestParameters": {
                    "instancesSet": {
                        "items": [
                            {"instanceId": "i-0123456789abcdef0"},
                            {"instanceId": "i-0abcdef0123456789"}
                        ]
                    }
                },
                "eventTime": "2024-01-15T10:30:00Z",
                "sourceIPAddress": "192.0.2.1",
                "userAgent": "aws-cli/2.0.0",
                "requestID": "example-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["user_arn"], "arn:aws:iam::123456789012:user/test-user")
        self.assertEqual(parsed["event_name"], "RunInstances")
        self.assertEqual(parsed["service"], "ec2")
        self.assertEqual(parsed["resource_type"], "instance")
        self.assertEqual(len(parsed["resource_ids"]), 2)
        self.assertIn("i-0123456789abcdef0", parsed["resource_ids"])

    def test_parse_create_bucket_event(self):
        """Test parsing S3 CreateBucket event"""
        event = {
            "detail": {
                "eventName": "CreateBucket",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/s3-admin"
                },
                "requestParameters": {
                    "bucketName": "my-test-bucket"
                },
                "eventTime": "2024-01-15T11:00:00Z",
                "sourceIPAddress": "192.0.2.2",
                "userAgent": "aws-cli/2.0.0",
                "requestID": "bucket-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["service"], "s3")
        self.assertEqual(parsed["resource_type"], "bucket")
        self.assertEqual(parsed["resource_ids"], ["my-test-bucket"])

    def test_parse_create_rds_instance_event(self):
        """Test parsing RDS CreateDBInstance event"""
        event = {
            "detail": {
                "eventName": "CreateDBInstance",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/dba-user"
                },
                "requestParameters": {
                    "dBInstanceIdentifier": "mydb-instance"
                },
                "eventTime": "2024-01-15T12:00:00Z",
                "sourceIPAddress": "192.0.2.3",
                "userAgent": "aws-console",
                "requestID": "rds-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["service"], "rds")
        self.assertEqual(parsed["resource_type"], "db")
        self.assertEqual(parsed["resource_ids"], ["mydb-instance"])

    def test_parse_root_user_event(self):
        """Test parsing event from root user"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "userIdentity": {
                    "type": "Root",
                    "accountId": "123456789012"
                },
                "requestParameters": {
                    "instancesSet": {
                        "items": [{"instanceId": "i-rootinstance"}]
                    }
                },
                "eventTime": "2024-01-15T13:00:00Z",
                "sourceIPAddress": "192.0.2.4",
                "requestID": "root-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["user_arn"], "arn:aws:iam::123456789012:root")

    def test_extract_user_arn_with_arn(self):
        """Test extracting user ARN when ARN is present"""
        user_identity = {
            "arn": "arn:aws:iam::123456789012:user/john.doe"
        }
        
        arn = CloudTrailParser._extract_user_arn({"userIdentity": user_identity})
        self.assertEqual(arn, "arn:aws:iam::123456789012:user/john.doe")

    def test_extract_user_arn_no_arn(self):
        """Test extracting user ARN when no ARN is available"""
        user_identity = {}
        
        arn = CloudTrailParser._extract_user_arn({"userIdentity": user_identity})
        self.assertIsNone(arn)

    def test_unsupported_event(self):
        """Test parsing unsupported event"""
        event = {
            "detail": {
                "eventName": "SomeUnsupportedEvent",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/test-user"
                }
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        self.assertIsNone(parsed)

    def test_missing_user_identity(self):
        """Test event with missing user identity"""
        event = {
            "detail": {
                "eventName": "RunInstances",
                "requestParameters": {
                    "instancesSet": {
                        "items": [{"instanceId": "i-test"}]
                    }
                }
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        self.assertIsNone(parsed)

    def test_supported_events_list(self):
        """Test getting list of supported events"""
        supported = CloudTrailParser.get_supported_events()
        
        self.assertIn("RunInstances", supported)
        self.assertIn("CreateBucket", supported)
        self.assertIn("CreateDBInstance", supported)
        self.assertIn("CreateFunction", supported)

    def test_is_supported_event(self):
        """Test checking if event is supported"""
        self.assertTrue(CloudTrailParser.is_supported_event("RunInstances"))
        self.assertTrue(CloudTrailParser.is_supported_event("CreateBucket"))
        self.assertFalse(CloudTrailParser.is_supported_event("DeleteInstance"))
        self.assertFalse(CloudTrailParser.is_supported_event("UnknownEvent"))

    def test_parse_lambda_function_creation(self):
        """Test parsing Lambda function creation event"""
        event = {
            "detail": {
                "eventName": "CreateFunction",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/lambda-dev"
                },
                "responseElements": {
                    "functionName": "my-lambda-function"
                },
                "eventTime": "2024-01-15T14:00:00Z",
                "sourceIPAddress": "192.0.2.5",
                "requestID": "lambda-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["service"], "lambda")
        self.assertEqual(parsed["resource_type"], "function")
        self.assertEqual(parsed["resource_ids"], ["my-lambda-function"])

    def test_parse_dynamodb_table_creation(self):
        """Test parsing DynamoDB table creation event"""
        event = {
            "detail": {
                "eventName": "CreateTable",
                "userIdentity": {
                    "arn": "arn:aws:iam::123456789012:user/dynamodb-admin"
                },
                "responseElements": {
                    "tableDescription": {
                        "tableName": "my-table"
                    }
                },
                "eventTime": "2024-01-15T15:00:00Z",
                "sourceIPAddress": "192.0.2.6",
                "requestID": "dynamodb-request-id"
            }
        }
        
        parsed = CloudTrailParser.parse_event(event)
        
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["service"], "dynamodb")
        self.assertEqual(parsed["resource_type"], "table")
        self.assertEqual(parsed["resource_ids"], ["my-table"])


if __name__ == "__main__":
    unittest.main()

