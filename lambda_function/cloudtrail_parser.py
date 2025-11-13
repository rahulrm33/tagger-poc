"""CloudTrail event parser for extracting resource information."""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class CloudTrailParser:
    """Parse CloudTrail events to extract resource IDs and user info."""

    EVENT_RESOURCE_MAPPING = {
        "RunInstances": {
            "service": "ec2",
            "resource_type": "instance",
            "id_path": ["responseElements", "instancesSet", "items"],
            "id_key": "instanceId"
        },
        "CreateVolume": {
            "service": "ec2",
            "resource_type": "volume",
            "id_path": ["responseElements", "volumeId"],
            "id_key": None
        },
        "CreateSnapshot": {
            "service": "ec2",
            "resource_type": "snapshot",
            "id_path": ["responseElements", "snapshotId"],
            "id_key": None
        },
        "CreateSecurityGroup": {
            "service": "ec2",
            "resource_type": "security-group",
            "id_path": ["responseElements", "groupId"],
            "id_key": None
        },

        # S3 Events
        "CreateBucket": {
            "service": "s3",
            "resource_type": "bucket",
            "id_path": ["requestParameters", "bucketName"],
            "id_key": None
        },

        # RDS Events
        "CreateDBInstance": {
            "service": "rds",
            "resource_type": "db",
            "id_path": ["requestParameters", "dBInstanceIdentifier"],
            "id_key": None
        },
        "CreateDBCluster": {
            "service": "rds",
            "resource_type": "cluster",
            "id_path": ["requestParameters", "dBClusterIdentifier"],
            "id_key": None
        },

        # Lambda Events
        "CreateFunction": {
            "service": "lambda",
            "resource_type": "function",
            "id_path": ["responseElements", "functionName"],
            "id_key": None
        },

        # DynamoDB Events
        "CreateTable": {
            "service": "dynamodb",
            "resource_type": "table",
            "id_path": ["responseElements", "tableDescription", "tableName"],
            "id_key": None
        },

        # SNS Events
        "CreateTopic": {
            "service": "sns",
            "resource_type": "topic",
            "id_path": ["responseElements", "topicArn"],
            "id_key": None
        },

        # SQS Events
        "CreateQueue": {
            "service": "sqs",
            "resource_type": "queue",
            "id_path": ["responseElements", "QueueUrl"],
            "id_key": None
        },
    }

    @staticmethod
    def parse_event(event: Dict) -> Optional[Dict]:
        """Parse CloudTrail event and extract resource information."""
        try:
            detail = event.get("detail", {})
            
            user_arn = CloudTrailParser._extract_user_arn(detail)
            if not user_arn:
                return None
            
            event_name = detail.get("eventName")
            if not event_name or event_name not in CloudTrailParser.EVENT_RESOURCE_MAPPING:
                return None
            
            resource_mapping = CloudTrailParser.EVENT_RESOURCE_MAPPING[event_name]
            resource_ids = CloudTrailParser._extract_resource_ids(detail, resource_mapping)
            
            if not resource_ids:
                return None
            
            return {
                "user_arn": user_arn,
                "event_name": event_name,
                "service": resource_mapping["service"],
                "resource_type": resource_mapping["resource_type"],
                "resource_ids": resource_ids,
                "event_time": detail.get("eventTime"),
                "region": detail.get("awsRegion"),
            }
            
        except Exception as e:
            logger.error(f"Parse error: {str(e)}")
            return None

    @staticmethod
    def _extract_user_arn(detail: Dict) -> Optional[str]:
        """Extract user ARN from userIdentity."""
        user_identity = detail.get("userIdentity", {})
        
        arn = user_identity.get("arn")
        if arn:
            return arn
        
        account_id = user_identity.get("accountId")
        if account_id and user_identity.get("type") == "Root":
            return f"arn:aws:iam::{account_id}:root"
        
        principal_id = user_identity.get("principalId")
        if principal_id:
            return principal_id
        
        return None

    @staticmethod
    def _extract_resource_ids(detail: Dict, resource_mapping: Dict) -> List[str]:
        """Extract resource IDs using configured path."""
        id_path = resource_mapping["id_path"]
        id_key = resource_mapping["id_key"]
        
        try:
            current = detail
            for path_part in id_path[:-1]:
                if isinstance(current, dict):
                    current = current.get(path_part, {})
                elif isinstance(current, list) and isinstance(path_part, int):
                    current = current[path_part]
                else:
                    return []
            
            final_key = id_path[-1]
            value = current.get(final_key) if isinstance(current, dict) else current
            
            if isinstance(value, list):
                if id_key:
                    return [item.get(id_key) for item in value if isinstance(item, dict) and item.get(id_key)]
                return [item for item in value if item]
            elif value:
                return [value]
            
            return []
            
        except Exception as e:
            logger.error(f"ID extraction error: {str(e)}")
            return []

    @staticmethod
    def is_supported_event(event_name: str) -> bool:
        return event_name in CloudTrailParser.EVENT_RESOURCE_MAPPING

    @staticmethod
    def get_supported_events() -> List[str]:
        return list(CloudTrailParser.EVENT_RESOURCE_MAPPING.keys())

