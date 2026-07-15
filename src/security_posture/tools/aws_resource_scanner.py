import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class AWSResourceScannerInput(BaseModel):
    """Input schema for AWSResourceScanner."""
    region: str = Field(default="us-east-1", description="AWS region to scan")


class AWSResourceScanner(BaseTool):
    name: str = "aws_resource_scanner"
    description: str = (
        "Scans an AWS account and returns a complete inventory of resources "
        "across EC2, S3, Lambda, IAM, Security Groups, API Gateway, and DynamoDB. "
        "Returns structured JSON with resource counts and details per service."
    )
    args_schema: Type[BaseModel] = AWSResourceScannerInput

    @trace_tool("aws_resource_scanner")
    def _run(self, region: str = "us-east-1") -> str:
        inventory = {}

        # EC2 Instances
        ec2 = boto3.client("ec2", region_name=region)
        instances = ec2.describe_instances()
        ec2_list = []
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                name = ""
                if instance.get("Tags"):
                    name = next(
                        (t["Value"] for t in instance["Tags"] if t["Key"] == "Name"), ""
                    )
                ec2_list.append({
                    "instance_id": instance["InstanceId"],
                    "name": name,
                    "type": instance["InstanceType"],
                    "state": instance["State"]["Name"],
                    "has_iam_profile": bool(instance.get("IamInstanceProfile")),
                    "security_groups": [sg["GroupId"] for sg in instance.get("SecurityGroups", [])],
                })
        inventory["ec2"] = {"count": len(ec2_list), "resources": ec2_list}

        # S3 Buckets
        s3 = boto3.client("s3", region_name=region)
        buckets = s3.list_buckets()
        s3_list = [{"name": b["Name"], "created": str(b["CreationDate"])} for b in buckets["Buckets"]]
        inventory["s3"] = {"count": len(s3_list), "resources": s3_list}

        # Lambda Functions
        lam = boto3.client("lambda", region_name=region)
        functions = lam.list_functions()
        lambda_list = [
            {
                "name": f["FunctionName"],
                "runtime": f.get("Runtime", "N/A"),
                "last_modified": f["LastModified"],
            }
            for f in functions["Functions"]
        ]
        inventory["lambda"] = {"count": len(lambda_list), "resources": lambda_list}

        # Security Groups
        sgs = ec2.describe_security_groups()
        sg_list = [
            {
                "group_id": sg["GroupId"],
                "name": sg["GroupName"],
                "description": sg["Description"],
                "vpc_id": sg.get("VpcId", ""),
            }
            for sg in sgs["SecurityGroups"]
        ]
        inventory["security_groups"] = {"count": len(sg_list), "resources": sg_list}

        # IAM Roles (count only for summary, details via iam_analyzer)
        iam = boto3.client("iam")
        roles = iam.list_roles(MaxItems=100)
        role_count = len(roles["Roles"])
        inventory["iam_roles"] = {"count": role_count, "note": "Use iam_analyzer tool for detailed analysis"}

        # IAM Users
        users = iam.list_users()
        user_list = [{"username": u["UserName"], "created": str(u["CreateDate"])} for u in users["Users"]]
        inventory["iam_users"] = {"count": len(user_list), "resources": user_list}

        # API Gateway
        apigw = boto3.client("apigateway", region_name=region)
        apis = apigw.get_rest_apis()
        api_list = [{"name": a["name"], "id": a["id"]} for a in apis["items"]]
        inventory["api_gateway"] = {"count": len(api_list), "resources": api_list}

        # DynamoDB
        ddb = boto3.client("dynamodb", region_name=region)
        tables = ddb.list_tables()
        inventory["dynamodb"] = {"count": len(tables["TableNames"]), "resources": tables["TableNames"]}

        # Total
        total = sum(svc["count"] for svc in inventory.values() if isinstance(svc, dict) and "count" in svc)
        inventory["total_resources"] = total

        return json.dumps(inventory, indent=2, default=str)
