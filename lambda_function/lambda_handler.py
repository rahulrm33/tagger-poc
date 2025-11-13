"""
AWS Auto-Tagging Lambda Handler
Main entry point for the Lambda function that processes CloudTrail events
and automatically tags resources with creator ARN
"""

import json
import logging
import os
from typing import Dict, Any
from cloudtrail_parser import CloudTrailParser
from tag_manager import TagManager

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuration
MAX_RETRIES = 3
BATCH_SIZE = 10


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for auto-tagging AWS resources
    
    Triggered by EventBridge when resources are created via CloudTrail events.
    
    Args:
        event: EventBridge event containing CloudTrail detail
        context: Lambda context object
        
    Returns:
        Response with tagging results
    """
    
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Parse CloudTrail event
        parsed_event = CloudTrailParser.parse_event(event)
        
        if not parsed_event:
            logger.warning("Could not parse event or event not supported")
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "message": "Event not supported or could not be parsed",
                    "event": event
                })
            }
        
        logger.info(f"Parsed event: {json.dumps(parsed_event)}")
        
        # Extract information
        user_arn = parsed_event["user_arn"]
        service = parsed_event["service"]
        resource_type = parsed_event["resource_type"]
        resource_ids = parsed_event["resource_ids"]
        event_name = parsed_event["event_name"]
        resource_region = parsed_event.get("region")  # Region where resource was created
        
        logger.info(
            f"Processing {service} resource creation: "
            f"user={user_arn}, event={event_name}, "
            f"resource_type={resource_type}, resource_count={len(resource_ids)}, "
            f"region={resource_region}"
        )
        
        # Initialize tag manager with Lambda's region as default
        lambda_region = os.environ.get("AWS_REGION", "us-east-1")
        tag_manager = TagManager(region=lambda_region)
        
        # Tag resources (will use resource's region from CloudTrail)
        tagged_resources, failed_resources = tag_manager.tag_resource(
            service=service,
            resource_type=resource_type,
            resource_ids=resource_ids,
            user_arn=user_arn,
            region=resource_region,
            additional_tags=_get_additional_tags(event)
        )
        
        # Prepare response
        response = {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Resource tagging completed",
                "event_name": event_name,
                "service": service,
                "resource_type": resource_type,
                "tagged_count": len(tagged_resources),
                "failed_count": len(failed_resources),
                "tagged_resources": tagged_resources,
                "failed_resources": failed_resources,
                "user_arn": user_arn,
                "timestamp": parsed_event.get("event_time")
            })
        }
        
        # Log summary
        logger.info(
            f"Tagging completed: {len(tagged_resources)} succeeded, "
            f"{len(failed_resources)} failed"
        )
        
        if failed_resources:
            logger.warning(f"Failed resources: {json.dumps(failed_resources)}")
        
        return response
        
    except Exception as e:
        logger.error(f"Unexpected error in lambda_handler: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": "Internal server error",
                "error": str(e)
            })
        }


def _get_additional_tags(event: Dict[str, Any]) -> Dict[str, str]:
    """
    Extract additional tags from event
    Can be customized to add organization-specific tags
    
    Args:
        event: The EventBridge event
        
    Returns:
        Dictionary of additional tags
    """
    additional_tags = {}
    
    detail = event.get("detail", {})
    
    # Add environment tag if available
    if os.environ.get("ENVIRONMENT"):
        additional_tags["Environment"] = os.environ.get("ENVIRONMENT")
    
    # Add source IP for audit trail
    source_ip = detail.get("sourceIPAddress")
    if source_ip:
        additional_tags["SourceIP"] = source_ip
    
    # Add account ID
    user_identity = detail.get("userIdentity", {})
    account_id = user_identity.get("accountId")
    if account_id:
        additional_tags["AccountId"] = account_id
    
    return additional_tags


def batch_tag_resources(
    parsed_events: list,
    tag_manager: TagManager
) -> Dict[str, Any]:
    """
    Batch process multiple resource tagging operations
    
    Args:
        parsed_events: List of parsed CloudTrail events
        tag_manager: TagManager instance
        
    Returns:
        Aggregated tagging results
    """
    all_tagged = []
    all_failed = []
    
    for parsed_event in parsed_events:
        tagged, failed = tag_manager.tag_resource(
            service=parsed_event["service"],
            resource_type=parsed_event["resource_type"],
            resource_ids=parsed_event["resource_ids"],
            user_arn=parsed_event["user_arn"],
            region=parsed_event.get("region"),
            additional_tags=_get_additional_tags({"detail": parsed_event})
        )
        
        all_tagged.extend(tagged)
        all_failed.extend(failed)
    
    return {
        "tagged_count": len(all_tagged),
        "failed_count": len(all_failed),
        "tagged_resources": all_tagged,
        "failed_resources": all_failed
    }


def health_check() -> Dict[str, Any]:
    """
    Simple health check for Lambda function
    
    Returns:
        Health status
    """
    return {
        "status": "healthy",
        "service": "AWS Auto-Tagger",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    # For local testing
    test_event = {
        "detail": {
            "eventName": "RunInstances",
            "userIdentity": {
                "arn": "arn:aws:iam::123456789012:user/test-user"
            },
            "requestParameters": {
                "instancesSet": {
                    "items": [
                        {"instanceId": "i-0123456789abcdef0"}
                    ]
                }
            },
            "eventTime": "2024-01-15T10:30:00Z",
            "sourceIPAddress": "192.0.2.1",
            "userAgent": "aws-cli/2.0.0",
            "requestID": "example-request-id"
        }
    }
    
    class MockContext:
        pass
    
    result = lambda_handler(test_event, MockContext())
    print(json.dumps(result, indent=2))

