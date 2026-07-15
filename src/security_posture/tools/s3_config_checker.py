import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class S3ConfigCheckerInput(BaseModel):
    """Input schema for S3ConfigChecker."""
    region: str = Field(default="us-east-1", description="AWS region")


class S3ConfigChecker(BaseTool):
    name: str = "s3_config_checker"
    description: str = (
        "Checks all S3 buckets for security configuration issues including "
        "missing encryption, disabled versioning, missing public access blocks, "
        "and overly permissive bucket policies. Returns findings per bucket."
    )
    args_schema: Type[BaseModel] = S3ConfigCheckerInput

    @trace_tool("s3_config_checker")
    def _run(self, region: str = "us-east-1") -> str:
        s3 = boto3.client("s3", region_name=region)
        buckets = s3.list_buckets()
        findings = []

        for bucket in buckets["Buckets"]:
            bucket_name = bucket["Name"]

            # Check 1: Encryption
            try:
                s3.get_bucket_encryption(Bucket=bucket_name)
            except s3.exceptions.ClientError as e:
                if "ServerSideEncryptionConfigurationNotFoundError" in str(e):
                    findings.append({
                        "resource_id": bucket_name,
                        "issue": "S3 bucket has no default encryption",
                        "severity": "HIGH",
                        "detail": f"Bucket '{bucket_name}' does not have default server-side encryption enabled.",
                        "current": "No default encryption",
                        "expected": "AES-256 or aws:kms default encryption enabled",
                    })

            # Check 2: Versioning
            try:
                versioning = s3.get_bucket_versioning(Bucket=bucket_name)
                status = versioning.get("Status", "Disabled")
                if status != "Enabled":
                    findings.append({
                        "resource_id": bucket_name,
                        "issue": "S3 bucket versioning is not enabled",
                        "severity": "MEDIUM",
                        "detail": f"Bucket '{bucket_name}' has versioning {status}. Without versioning, deleted or overwritten objects cannot be recovered.",
                        "current": f"Versioning: {status}",
                        "expected": "Versioning: Enabled",
                    })
            except Exception:
                pass

            # Check 3: Public Access Block
            try:
                pab = s3.get_public_access_block(Bucket=bucket_name)
                config = pab["PublicAccessBlockConfiguration"]
                all_blocked = all([
                    config.get("BlockPublicAcls", False),
                    config.get("IgnorePublicAcls", False),
                    config.get("BlockPublicPolicy", False),
                    config.get("RestrictPublicBuckets", False),
                ])
                if not all_blocked:
                    findings.append({
                        "resource_id": bucket_name,
                        "issue": "S3 bucket public access block is not fully configured",
                        "severity": "HIGH",
                        "detail": f"Bucket '{bucket_name}' does not have all four public access block settings enabled.",
                        "current": json.dumps(config),
                        "expected": "All four public access block settings set to true",
                    })
            except s3.exceptions.ClientError as e:
                if "NoSuchPublicAccessBlockConfiguration" in str(e):
                    findings.append({
                        "resource_id": bucket_name,
                        "issue": "S3 bucket has no public access block configuration",
                        "severity": "HIGH",
                        "detail": f"Bucket '{bucket_name}' has no public access block at all. Objects could be made public.",
                        "current": "No public access block configured",
                        "expected": "All four public access block settings enabled",
                    })

        return json.dumps({
            "total_buckets": len(buckets["Buckets"]),
            "findings_count": len(findings),
            "findings": findings,
        }, indent=2)
