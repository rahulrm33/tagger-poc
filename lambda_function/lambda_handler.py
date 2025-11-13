"""Auto-tagging Lambda handler for CloudTrail events."""

import json
import logging
import os
from typing import Dict, Any
from cloudtrail_parser import CloudTrailParser
from tag_manager import TagManager
from s3_cloudtrail_processor import S3CloudTrailProcessor

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Process S3 CloudTrail logs and tag resources."""
    try:
        if not S3CloudTrailProcessor.is_s3_event(event):
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid event type"})}
        
        return handle_s3_event(event)
        
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


def handle_s3_event(s3_event: Dict[str, Any]) -> Dict[str, Any]:
    """Process CloudTrail logs from S3."""
    processor = S3CloudTrailProcessor()
    cloudtrail_events = processor.process_s3_event(s3_event)
    
    if not cloudtrail_events:
        return {"statusCode": 200, "body": json.dumps({"events_processed": 0})}
    
    logger.info(f"Processing {len(cloudtrail_events)} events")
    
    results = []
    for event in cloudtrail_events:
        result = process_single_event(event)
        if result:
            results.append(result)
    
    total_tagged = sum(r.get('tagged_count', 0) for r in results)
    total_failed = sum(r.get('failed_count', 0) for r in results)
    
    return {
        "statusCode": 200,
        "body": json.dumps({
            "events_processed": len(cloudtrail_events),
            "total_tagged": total_tagged,
            "total_failed": total_failed
        })
    }


def process_single_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Process and tag resources from a single CloudTrail event."""
    parsed_event = CloudTrailParser.parse_event(event)
    if not parsed_event:
        return None
    
    user_arn = parsed_event["user_arn"]
    service = parsed_event["service"]
    resource_type = parsed_event["resource_type"]
    resource_ids = parsed_event["resource_ids"]
    resource_region = parsed_event.get("region")
    
    logger.info(f"Tagging {service} resources in {resource_region}")
    
    lambda_region = os.environ.get("AWS_REGION", "us-east-1")
    tag_manager = TagManager(region=lambda_region)
    
    tagged_resources, failed_resources = tag_manager.tag_resource(
        service=service,
        resource_type=resource_type,
        resource_ids=resource_ids,
        user_arn=user_arn,
        region=resource_region,
        additional_tags=_get_additional_tags(event)
    )
    
    if failed_resources:
        logger.warning(f"Failed: {len(failed_resources)} resources")
    
    return {
        "event_name": parsed_event["event_name"],
        "service": service,
        "resource_region": resource_region,
        "tagged_count": len(tagged_resources),
        "failed_count": len(failed_resources),
        "user_arn": user_arn
    }


def _get_additional_tags(event: Dict[str, Any]) -> Dict[str, str]:
    """Extract additional tags from CloudTrail event."""
    tags = {}
    detail = event.get("detail", {})
    
    env = os.environ.get("ENVIRONMENT")
    if env:
        tags["Environment"] = env
    
    source_ip = detail.get("sourceIPAddress")
    if source_ip:
        tags["SourceIP"] = source_ip
    
    account_id = detail.get("userIdentity", {}).get("accountId")
    if account_id:
        tags["AccountId"] = account_id
    
    return tags



