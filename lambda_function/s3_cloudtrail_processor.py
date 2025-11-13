"""
S3 CloudTrail Log Processor
Processes CloudTrail logs from S3 to extract resource creation events
Enables single-region Lambda to handle multi-region resource tagging
"""

import json
import gzip
import logging
from typing import Dict, List, Any, Optional
import boto3
from io import BytesIO

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class S3CloudTrailProcessor:
    """Process CloudTrail logs stored in S3"""
    
    def __init__(self):
        self.s3_client = boto3.client('s3')
    
    def process_s3_event(self, s3_event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process S3 event notification to extract CloudTrail events
        
        Args:
            s3_event: S3 event notification from Lambda trigger
            
        Returns:
            List of CloudTrail events ready for processing
        """
        cloudtrail_events = []
        
        # S3 event can contain multiple records
        for record in s3_event.get('Records', []):
            try:
                # Extract S3 bucket and key information
                bucket = record['s3']['bucket']['name']
                key = record['s3']['object']['key']
                
                logger.info(f"Processing CloudTrail log from s3://{bucket}/{key}")
                
                # Download and parse CloudTrail log file
                events = self._download_and_parse_log(bucket, key)
                cloudtrail_events.extend(events)
                
            except Exception as e:
                logger.error(f"Error processing S3 record: {str(e)}", exc_info=True)
                continue
        
        logger.info(f"Extracted {len(cloudtrail_events)} CloudTrail events from S3")
        return cloudtrail_events
    
    def _download_and_parse_log(self, bucket: str, key: str) -> List[Dict[str, Any]]:
        """
        Download CloudTrail log file from S3 and parse it
        
        CloudTrail log files are gzip-compressed JSON files
        
        Args:
            bucket: S3 bucket name
            key: S3 object key
            
        Returns:
            List of CloudTrail records
        """
        try:
            # Download the log file
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            
            # CloudTrail logs are gzipped
            with gzip.GzipFile(fileobj=BytesIO(response['Body'].read())) as gzipfile:
                content = gzipfile.read()
                log_data = json.loads(content)
            
            # CloudTrail log structure: {"Records": [events...]}
            records = log_data.get('Records', [])
            
            # Filter for resource creation events
            filtered_records = self._filter_creation_events(records)
            
            logger.info(
                f"Parsed {len(records)} records, "
                f"{len(filtered_records)} are resource creation events"
            )
            
            return filtered_records
            
        except Exception as e:
            logger.error(f"Error downloading/parsing log from s3://{bucket}/{key}: {str(e)}")
            return []
    
    def _filter_creation_events(self, records: List[Dict]) -> List[Dict]:
        """
        Filter CloudTrail records to only resource creation events
        
        Args:
            records: Raw CloudTrail records
            
        Returns:
            Filtered list of creation events
        """
        # Events we care about
        CREATION_EVENTS = {
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
        }
        
        filtered = []
        for record in records:
            event_name = record.get('eventName')
            
            # Only process creation events
            if event_name not in CREATION_EVENTS:
                continue
            
            # Skip failed events (errorCode present)
            if record.get('errorCode'):
                logger.debug(f"Skipping failed event: {event_name} - {record.get('errorCode')}")
                continue
            
            # Convert CloudTrail record to EventBridge-like format
            event = self._convert_to_eventbridge_format(record)
            if event:
                filtered.append(event)
        
        return filtered
    
    def _convert_to_eventbridge_format(self, cloudtrail_record: Dict) -> Optional[Dict]:
        """
        Convert raw CloudTrail record to EventBridge event format
        
        This allows us to reuse the existing CloudTrailParser
        
        Args:
            cloudtrail_record: Raw CloudTrail record from S3 log
            
        Returns:
            EventBridge-formatted event or None
        """
        try:
            # EventBridge format that matches what our existing parser expects
            event = {
                "version": "0",
                "id": cloudtrail_record.get('eventID'),
                "detail-type": "AWS API Call via CloudTrail",
                "source": f"aws.{cloudtrail_record.get('eventSource', '').split('.')[0]}",
                "account": cloudtrail_record.get('recipientAccountId'),
                "time": cloudtrail_record.get('eventTime'),
                "region": cloudtrail_record.get('awsRegion'),
                "detail": cloudtrail_record
            }
            
            return event
            
        except Exception as e:
            logger.error(f"Error converting CloudTrail record: {str(e)}")
            return None
    
    @staticmethod
    def is_s3_event(event: Dict) -> bool:
        """
        Check if Lambda event is from S3
        
        Args:
            event: Lambda event
            
        Returns:
            True if event is from S3
        """
        # S3 events have Records with s3 key
        if 'Records' in event:
            for record in event['Records']:
                if 's3' in record:
                    return True
        return False
    
    @staticmethod
    def is_eventbridge_event(event: Dict) -> bool:
        """
        Check if Lambda event is from EventBridge
        
        Args:
            event: Lambda event
            
        Returns:
            True if event is from EventBridge
        """
        return 'detail' in event and 'detail-type' in event


if __name__ == "__main__":
    # Test with sample S3 event
    processor = S3CloudTrailProcessor()
    
    sample_s3_event = {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "test-cloudtrail-bucket"
                    },
                    "object": {
                        "key": "AWSLogs/123456789012/CloudTrail/us-east-1/2024/01/15/test.json.gz"
                    }
                }
            }
        ]
    }
    
    print(f"Is S3 event: {processor.is_s3_event(sample_s3_event)}")
    print(f"Is EventBridge event: {processor.is_eventbridge_event(sample_s3_event)}")

