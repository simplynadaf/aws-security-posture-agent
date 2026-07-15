import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class EC2SecurityCheckerInput(BaseModel):
    """Input schema for EC2SecurityChecker."""
    region: str = Field(default="us-east-1", description="AWS region to scan")


class EC2SecurityChecker(BaseTool):
    name: str = "ec2_security_checker"
    description: str = (
        "Checks EC2 instances for security issues including missing IAM instance profiles, "
        "instances with public IPs that may not need them, unencrypted EBS volumes, "
        "instances using default security groups, and stopped instances still incurring costs. "
        "Returns findings per instance."
    )
    args_schema: Type[BaseModel] = EC2SecurityCheckerInput

    @trace_tool("ec2_security_checker")
    def _run(self, region: str = "us-east-1") -> str:
        ec2 = boto3.client("ec2", region_name=region)
        findings = []

        # Get all instances
        instances = ec2.describe_instances()
        instance_list = []
        for reservation in instances["Reservations"]:
            for inst in reservation["Instances"]:
                instance_list.append(inst)

        for inst in instance_list:
            instance_id = inst["InstanceId"]
            state = inst["State"]["Name"]
            name = ""
            if inst.get("Tags"):
                name = next((t["Value"] for t in inst["Tags"] if t["Key"] == "Name"), "")

            display_name = f"{name} ({instance_id})" if name else instance_id

            # Check 1: No IAM Instance Profile
            if not inst.get("IamInstanceProfile") and state == "running":
                findings.append({
                    "resource_id": instance_id,
                    "resource_name": display_name,
                    "issue": "Running EC2 instance has no IAM instance profile",
                    "severity": "HIGH",
                    "detail": f"Instance '{display_name}' is running without an IAM role. Applications on this instance cannot use AWS SDK with instance credentials and may have hardcoded keys.",
                    "current": "No IAM instance profile attached",
                    "expected": "IAM instance profile with least-privilege role",
                })

            # Check 2: Public IP on non-web instances
            if inst.get("PublicIpAddress") and state == "running":
                # Check if it's behind a known web-facing SG (ports 80/443)
                findings.append({
                    "resource_id": instance_id,
                    "resource_name": display_name,
                    "issue": "EC2 instance has a public IP address",
                    "severity": "MEDIUM",
                    "detail": f"Instance '{display_name}' has public IP {inst['PublicIpAddress']}. Verify this instance needs direct internet exposure. Consider using a load balancer or bastion host.",
                    "current": f"Public IP: {inst['PublicIpAddress']}",
                    "expected": "Private subnet with NAT Gateway, or justified public access via ALB",
                })

            # Check 3: Instance using default security group
            for sg in inst.get("SecurityGroups", []):
                if sg["GroupName"] == "default":
                    findings.append({
                        "resource_id": instance_id,
                        "resource_name": display_name,
                        "issue": "Instance attached to default security group",
                        "severity": "HIGH",
                        "detail": f"Instance '{display_name}' uses the default SG ({sg['GroupId']}). Default SGs are often overly permissive and shared across resources.",
                        "current": f"Attached to default SG: {sg['GroupId']}",
                        "expected": "Purpose-built security group with minimal rules",
                    })

        # Check 4: Unencrypted EBS volumes
        volumes = ec2.describe_volumes()
        for vol in volumes["Volumes"]:
            if not vol.get("Encrypted", False):
                vol_id = vol["VolumeId"]
                attached_to = ""
                if vol.get("Attachments"):
                    attached_to = vol["Attachments"][0].get("InstanceId", "unattached")
                findings.append({
                    "resource_id": vol_id,
                    "resource_name": f"EBS {vol_id}",
                    "issue": "EBS volume is not encrypted",
                    "severity": "HIGH",
                    "detail": f"Volume '{vol_id}' (attached to {attached_to}) is not encrypted at rest. Data could be exposed if the volume or snapshot is accessed.",
                    "current": "Encrypted: False",
                    "expected": "Encrypted: True (AES-256 or aws:kms)",
                })

        # Check 5: Stopped instances (cost waste, potential stale resources)
        stopped = [i for i in instance_list if i["State"]["Name"] == "stopped"]
        if stopped:
            for inst in stopped:
                instance_id = inst["InstanceId"]
                name = ""
                if inst.get("Tags"):
                    name = next((t["Value"] for t in inst["Tags"] if t["Key"] == "Name"), "")
                display_name = f"{name} ({instance_id})" if name else instance_id
                findings.append({
                    "resource_id": instance_id,
                    "resource_name": display_name,
                    "issue": "EC2 instance is stopped but still exists",
                    "severity": "LOW",
                    "detail": f"Instance '{display_name}' is stopped. EBS volumes still incur charges. Consider terminating if no longer needed or creating an AMI backup.",
                    "current": "State: stopped",
                    "expected": "Terminate if unused, or document justification for keeping",
                })

        return json.dumps({
            "total_instances": len(instance_list),
            "total_volumes": len(volumes["Volumes"]),
            "findings_count": len(findings),
            "findings": findings,
        }, indent=2, default=str)
