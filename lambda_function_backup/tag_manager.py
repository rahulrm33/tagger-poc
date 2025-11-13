"""
Tag Manager
Handles applying tags to AWS resources across different services
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class TagManager:
    """Manage resource tagging across multiple AWS services"""

    # Service-specific tag clients and methods
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
        """Initialize TagManager with AWS clients"""
        self.region = region
        self.clients = {}
        self.tagged_resources = []
        self.failed_resources = []

    def _get_client(self, service: str):
        """Get or create boto3 client for service"""
        if service not in self.clients:
            self.clients[service] = boto3.client(service, region_name=self.region)
        return self.clients[service]

    def tag_resource(
        self,
        service: str,
        resource_type: str,
        resource_ids: List[str],
        user_arn: str,
        additional_tags: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """
        Tag a resource with creator information
        
        Args:
            service: AWS service (ec2, s3, rds, etc.)
            resource_type: Type of resource
            resource_ids: List of resource IDs to tag
            user_arn: ARN of user who created the resource
            additional_tags: Optional additional tags to apply
            
        Returns:
            Tuple of (tagged_resource_ids, failed_resources)
        """
        if service not in self.SUPPORTED_SERVICES:
            logger.error(f"Service '{service}' not supported")
            return [], [{"resource_id": rid, "error": "Unsupported service"} for rid in resource_ids]

        try:
            method_name = self.SUPPORTED_SERVICES[service]["tag_method"]
            method = getattr(self, method_name, None)
            
            if not method:
                logger.error(f"Tag method not found for service '{service}'")
                return [], [{"resource_id": rid, "error": "Method not found"} for rid in resource_ids]
            
            return method(resource_ids, user_arn, resource_type, additional_tags)
            
        except Exception as e:
            logger.error(f"Error tagging {service} resource: {str(e)}")
            return [], [{"resource_id": rid, "error": str(e)} for rid in resource_ids]

    def _build_tags(self, user_arn: str, additional_tags: Optional[Dict] = None) -> Dict[str, str]:
        """Build tag dictionary with creator info"""
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
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag EC2 resources (instances, volumes, snapshots, security groups)"""
        client = self._get_client("ec2")
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to EC2 tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for resource_id in resource_ids:
            try:
                client.create_tags(Resources=[resource_id], Tags=tag_list)
                tagged.append(resource_id)
                logger.info(f"Tagged EC2 {resource_type} '{resource_id}' with creator: {user_arn}")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": resource_id, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag EC2 resource '{resource_id}': {error_msg}")
        
        return tagged, failed

    def _tag_s3_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag S3 buckets"""
        client = self._get_client("s3")
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to S3 tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        tag_set = {"TagSet": tag_list}
        
        tagged = []
        failed = []
        
        for bucket_name in resource_ids:
            try:
                client.put_bucket_tagging(Bucket=bucket_name, Tagging=tag_set)
                tagged.append(bucket_name)
                logger.info(f"Tagged S3 bucket '{bucket_name}' with creator: {user_arn}")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": bucket_name, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag S3 bucket '{bucket_name}': {error_msg}")
        
        return tagged, failed

    def _tag_rds_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag RDS resources (DB instances, clusters)"""
        client = self._get_client("rds")
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to RDS tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for resource_id in resource_ids:
            try:
                # Build ARN based on resource type
                if resource_type == "db":
                    arn = f"arn:aws:rds:{self.region}:*:db:{resource_id}"
                elif resource_type == "cluster":
                    arn = f"arn:aws:rds:{self.region}:*:cluster:{resource_id}"
                else:
                    arn = resource_id
                
                client.add_tags_to_resource(ResourceName=arn, Tags=tag_list)
                tagged.append(resource_id)
                logger.info(f"Tagged RDS {resource_type} '{resource_id}' with creator: {user_arn}")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": resource_id, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag RDS resource '{resource_id}': {error_msg}")
        
        return tagged, failed

    def _tag_lambda_resource(
        self,
        resource_ids: List[str],
        user_arn: str,
        resource_type: str,
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag Lambda functions"""
        client = self._get_client("lambda")
        tags = self._build_tags(user_arn, additional_tags)
        
        tagged = []
        failed = []
        
        for function_name in resource_ids:
            try:
                client.tag_resource(Resource=function_name, Tags=tags)
                tagged.append(function_name)
                logger.info(f"Tagged Lambda function '{function_name}' with creator: {user_arn}")
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
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag DynamoDB tables"""
        client = self._get_client("dynamodb")
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
                logger.info(f"Tagged DynamoDB table '{table_name}' with creator: {user_arn}")
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
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag SNS topics"""
        client = self._get_client("sns")
        tags = self._build_tags(user_arn, additional_tags)
        
        # Convert to SNS tag format
        tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
        
        tagged = []
        failed = []
        
        for topic_arn in resource_ids:
            try:
                client.tag_resource(ResourceArn=topic_arn, Tags=tag_list)
                tagged.append(topic_arn)
                logger.info(f"Tagged SNS topic '{topic_arn}' with creator: {user_arn}")
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
        additional_tags: Optional[Dict] = None,
    ) -> Tuple[List[str], List[Dict]]:
        """Tag SQS queues"""
        client = self._get_client("sqs")
        tags = self._build_tags(user_arn, additional_tags)
        
        tagged = []
        failed = []
        
        for queue_url in resource_ids:
            try:
                client.tag_queue_async(QueueUrl=queue_url, Tags=tags)
                tagged.append(queue_url)
                logger.info(f"Tagged SQS queue '{queue_url}' with creator: {user_arn}")
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                error_msg = e.response["Error"]["Message"]
                failed.append({"resource_id": queue_url, "error": f"{error_code}: {error_msg}"})
                logger.error(f"Failed to tag SQS queue '{queue_url}': {error_msg}")
        
        return tagged, failed

