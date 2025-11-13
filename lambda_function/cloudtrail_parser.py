"""
CloudTrail Event Parser
Extracts relevant information from CloudTrail events for resource tagging
"""

import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class CloudTrailParser:
    """Parse CloudTrail events and extract resource creation information"""

    # Mapping of EventName to service and resource identifiers
    EVENT_RESOURCE_MAPPING = {
        # EC2 Events
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
        """
        Parse CloudTrail event and extract relevant information
        
        Args:
            event: CloudTrail event from EventBridge
            
        Returns:
            Dictionary with parsed information or None if not supported
        """
        try:
            detail = event.get("detail", {})
            
            # Extract user ARN
            user_arn = CloudTrailParser._extract_user_arn(detail)
            if not user_arn:
                logger.warning("Could not extract user ARN from event")
                return None
            
            # Extract event name
            event_name = detail.get("eventName")
            if not event_name or event_name not in CloudTrailParser.EVENT_RESOURCE_MAPPING:
                logger.debug(f"Event '{event_name}' not in supported events")
                return None
            
            # Extract resource information
            resource_mapping = CloudTrailParser.EVENT_RESOURCE_MAPPING[event_name]
            resource_ids = CloudTrailParser._extract_resource_ids(
                detail,
                resource_mapping
            )
            
            if not resource_ids:
                logger.warning(f"Could not extract resource IDs for event '{event_name}'")
                return None
            
            return {
                "user_arn": user_arn,
                "event_name": event_name,
                "service": resource_mapping["service"],
                "resource_type": resource_mapping["resource_type"],
                "resource_ids": resource_ids,
                "event_time": detail.get("eventTime"),
                "source_ip": detail.get("sourceIPAddress"),
                "user_agent": detail.get("userAgent"),
                "request_id": detail.get("requestID"),
                "region": detail.get("awsRegion"),  # Extract region where resource was created
            }
            
        except Exception as e:
            logger.error(f"Error parsing CloudTrail event: {str(e)}", exc_info=True)
            return None

    @staticmethod
    def _extract_user_arn(detail: Dict) -> Optional[str]:
        """
        Extract user ARN from CloudTrail event
        
        Handles different user types:
        - IAM Users
        - IAM Roles (assumed)
        - Root account
        """
        user_identity = detail.get("userIdentity", {})
        
        # Try to get ARN directly
        arn = user_identity.get("arn")
        if arn:
            return arn
        
        # For root account access
        account_id = user_identity.get("accountId")
        if account_id and user_identity.get("type") == "Root":
            return f"arn:aws:iam::{account_id}:root"
        
        # Try to construct ARN from available info
        principal_id = user_identity.get("principalId")
        if principal_id and ":" in principal_id:
            # Principal ID format: "AIDAI23HXD2O7EXAMPLE:session-name"
            parts = principal_id.split(":")
            access_key_id = parts[0]
            # This is a role assumption, we got what we can
            return principal_id
        
        return None

    @staticmethod
    def _extract_resource_ids(detail: Dict, resource_mapping: Dict) -> List[str]:
        """
        Extract resource IDs from CloudTrail event using path configuration
        
        Args:
            detail: CloudTrail event detail
            resource_mapping: Mapping configuration for this event type
            
        Returns:
            List of resource IDs
        """
        resource_ids = []
        id_path = resource_mapping["id_path"]
        id_key = resource_mapping["id_key"]
        
        try:
            # Navigate through nested dictionaries using the path
            current = detail
            for path_part in id_path[:-1]:
                if isinstance(current, dict):
                    current = current.get(path_part, {})
                elif isinstance(current, list) and isinstance(path_part, int):
                    current = current[path_part]
                else:
                    return []
            
            # Get the final value
            final_key = id_path[-1]
            if isinstance(current, dict):
                value = current.get(final_key)
            elif isinstance(current, list):
                value = current
            else:
                return []
            
            # Extract resource IDs based on whether it's a list or dict
            if isinstance(value, list):
                if id_key:
                    # List of dicts with id_key
                    resource_ids = [item.get(id_key) for item in value if isinstance(item, dict) and item.get(id_key)]
                else:
                    # List of IDs
                    resource_ids = [item for item in value if item]
            elif value:
                # Single value
                resource_ids = [value]
            
            return [rid for rid in resource_ids if rid]  # Filter out None/empty values
            
        except Exception as e:
            logger.error(f"Error extracting resource IDs: {str(e)}")
            return []

    @staticmethod
    def is_supported_event(event_name: str) -> bool:
        """Check if event is supported for auto-tagging"""
        return event_name in CloudTrailParser.EVENT_RESOURCE_MAPPING

    @staticmethod
    def get_supported_events() -> List[str]:
        """Get list of all supported event names"""
        return list(CloudTrailParser.EVENT_RESOURCE_MAPPING.keys())

