"""S3 CloudTrail log processor."""

import json
import gzip
import logging
from typing import Dict, List, Any, Optional
import boto3
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class S3CloudTrailProcessor:
    """Process CloudTrail logs from S3."""
    
    def __init__(self):
        self.s3_client = boto3.client('s3')
    
    def process_s3_event(self, s3_event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract CloudTrail events from S3 log files."""
        cloudtrail_events = []
        
        for record in s3_event.get('Records', []):
            try:
                bucket = record['s3']['bucket']['name']
                key = record['s3']['object']['key']
                events = self._download_and_parse_log(bucket, key)
                cloudtrail_events.extend(events)
            except Exception as e:
                logger.error(f"S3 processing error: {str(e)}")
                continue
        
        return cloudtrail_events
    
    def _download_and_parse_log(self, bucket: str, key: str) -> List[Dict[str, Any]]:
        """Download and parse CloudTrail log file."""
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            with gzip.GzipFile(fileobj=BytesIO(response['Body'].read())) as gzipfile:
                log_data = json.loads(gzipfile.read())
            
            records = log_data.get('Records', [])
            return self._filter_creation_events(records)
            
        except Exception as e:
            logger.error(f"Log parse error: {str(e)}")
            return []
    
    def _filter_creation_events(self, records: List[Dict]) -> List[Dict]:
        """Filter for resource creation events."""
        CREATION_EVENTS = {
            "RunInstances", "CreateVolume", "CreateSnapshot", "CreateSecurityGroup",
            "CreateBucket", "CreateDBInstance", "CreateDBCluster", "CreateFunction",
            "CreateTable", "CreateTopic", "CreateQueue"
        }
        
        filtered = []
        for record in records:
            event_name = record.get('eventName')
            if event_name in CREATION_EVENTS and not record.get('errorCode'):
                event = self._convert_to_eventbridge_format(record)
                if event:
                    filtered.append(event)
        
        return filtered
    
    def _convert_to_eventbridge_format(self, cloudtrail_record: Dict) -> Optional[Dict]:
        """Convert CloudTrail record to standardized format."""
        try:
            return {
                "version": "0",
                "id": cloudtrail_record.get('eventID'),
                "detail-type": "AWS API Call via CloudTrail",
                "source": f"aws.{cloudtrail_record.get('eventSource', '').split('.')[0]}",
                "account": cloudtrail_record.get('recipientAccountId'),
                "time": cloudtrail_record.get('eventTime'),
                "region": cloudtrail_record.get('awsRegion'),
                "detail": cloudtrail_record
            }
        except Exception as e:
            logger.error(f"Conversion error: {str(e)}")
            return None
    
    @staticmethod
    def is_s3_event(event: Dict) -> bool:
        """Check if event is from S3."""
        if 'Records' in event:
            return any('s3' in record for record in event['Records'])
        return False

