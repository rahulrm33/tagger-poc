"""Tag manager for AWS resources."""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class TagManager:
    """Manages tagging across AWS services."""

    SUPPORTED_SERVICES = {
        "ec2": {
            "client": "ec2",
            "tag_method": "_tag_ec2_resource",
        },
        "s3": {
            "client": "s3",
            "tag_method": "_tag_s3_resource",
        },
        "rds": {
            "client": "rds",
            "tag_method": "_tag_rds_resource",
        },
        "lambda": {
            "client": "lambda",
            "tag_method": "_tag_lambda_resource",
        },
        "dynamodb": {
            "client": "dynamodb",
            "tag_method": "_tag_dynamodb_resource",
        },
        "sns": {
            "client": "sns",
            "tag_method": "_tag_sns_resource",
        },
        "sqs": {
            "client": "sqs",
            "tag_method": "_tag_sqs_resource",
        },
    }

    def __init__(self, region: str = "us-east-1"):
        self.default_region = region
        self.clients = {}
        self.tagged_resources = []
        self.failed_resources = []

    def _get_client(self, service: str, region: str = None):
        """Get or create boto3 client."""
        region = region or self.default_region
        client_key = f"{service}_{region}"
        if client_key not in self.clients:
            self.clients[client_key] = boto3.client(service, region_name=region)
        return self.clients[client_key]

    def tag_resource(
        self,
        service: str,
        resource_type: str,
        resource_ids: List[str],
        user_arn: str,
        region: str = None,
        additional_tags: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag resources with creator information."""
        if service not in self.SUPPORTED_SERVICES:
            return [], [{"resource_id": rid, "error": "Unsupported service"} for rid in resource_ids]

        try:
            method_name = self.SUPPORTED_SERVICES[service]["tag_method"]
            method = getattr(self, method_name, None)
            if not method:
                return [], [{"resource_id": rid, "error": "Method not found"} for rid in resource_ids]
            
            return method(resource_ids, user_arn, resource_type, region, additional_tags)
            
        except Exception as e:
            logger.error(f"Tagging error: {str(e)}")
            return [], [{"resource_id": rid, "error": str(e)} for rid in resource_ids]

    def _build_tags(self, user_arn: str, additional_tags: Optional[Dict] = None) -> Dict[str, str]:
        """Build tag dictionary."""
        tags = {
            "CreatedBy": user_arn,
            "CreatedDate": datetime.utcnow().isoformat(),
            "ManagedBy": "auto-tagger",
        }
        if additional_tags:
            tags.update(additional_tags)
        return tags

    def _tag_ec2_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        client = self._get_client("ec2", region)
        tags = self._build_tags(user_arn, additional_tags)
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged, failed = [], []
        for resource_id in resource_ids:
            try:
                client.create_tags(Resources=[resource_id], Tags=tag_list)
                tagged.append(resource_id)
            except ClientError as e:
                failed.append({"resource_id": resource_id, "error": e.response["Error"]["Code"]})
        
        return tagged, failed

    def _tag_s3_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        client = self._get_client("s3", region)
        tags = self._build_tags(user_arn, additional_tags)
        tag_set = {"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]}
        
        tagged, failed = [], []
        for bucket_name in resource_ids:
            try:
                client.put_bucket_tagging(Bucket=bucket_name, Tagging=tag_set)
                tagged.append(bucket_name)
            except ClientError as e:
                failed.append({"resource_id": bucket_name, "error": e.response["Error"]["Code"]})
        
        return tagged, failed

    def _tag_rds_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag RDS resources (DB instances, clusters)"""
        if region is None:
            region = self.default_region
        client = self._get_client("rds", region)
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to RDS tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for resource_id in resource_ids:
            try:
                # Build ARN based on resource type
                if resource_type == "db":
                    arn = f"arn:aws:rds:{region}:*:db:{resource_id}"
                elif resource_type == "cluster":
                    arn = f"arn:aws:rds:{region}:*:cluster:{resource_id}"
                else:
                    arn = resource_id
                
                client.add_tags_to_resource(ResourceName=arn, Tags=tag_list)
                tagged.append(resource_id)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": resource_id, "error": f"{error_code}: {error_msg}"})
        
        return tagged, failed

    def _tag_lambda_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag Lambda functions"""
        client = self._get_client("lambda", region)
        tags = self._build_tags(user_arn, additional_tags)
        
        tagged = []
        failed = []
        
        for function_name in resource_ids:
            try:
                client.tag_resource(Resource=function_name, Tags=tags)
                tagged.append(function_name)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": function_name, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag Lambda function '{function_name}': {error_msg}")
        
        return tagged, failed

    def _tag_dynamodb_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag DynamoDB tables"""
        client = self._get_client("dynamodb", region)
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to DynamoDB tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for table_name in resource_ids:
            try:
                # Get table ARN
                response = client.describe_table(TableName=table_name)
                table_arn = response["Table"]["TableArn"]
                
                client.tag_resource(ResourceArn=table_arn, Tags=tag_list)
                tagged.append(table_name)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": table_name, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag DynamoDB table '{table_name}': {error_msg}")
        
        return tagged, failed

    def _tag_sns_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag SNS topics"""
        client = self._get_client("sns", region)
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to SNS tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for topic_arn in resource_ids:
            try:
                client.tag_resource(ResourceArn=topic_arn, Tags=tag_list)
                tagged.append(topic_arn)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": topic_arn, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag SNS topic '{topic_arn}': {error_msg}")
        
        return tagged, failed

    def _tag_sqs_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        region: str = None,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag SQS queues"""
        client = self._get_client("sqs", region)
        tags = self._build_tags(user_arn, additional_tags)
        
        tagged = []
        failed = []
        
        for queue_url in resource_ids:
            try:
                client.tag_queue_async(QueueUrl=queue_url, Tags=tags)
                tagged.append(queue_url)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": queue_url, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag SQS queue '{queue_url}': {error_msg}")
        
        return tagged, failed

