import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class SecurityGroupAnalyzerInput(BaseModel):
    """Input schema for SecurityGroupAnalyzer."""
    region: str = Field(default="us-east-1", description="AWS region to scan")


class SecurityGroupAnalyzer(BaseTool):
    name: str = "security_group_analyzer"
    description: str = (
        "Analyzes all security groups for dangerous configurations including "
        "overly permissive ingress rules (0.0.0.0/0), wide port ranges, "
        "default security groups with custom rules, and stale launch-wizard groups. "
        "Returns findings with severity ratings."
    )
    args_schema: Type[BaseModel] = SecurityGroupAnalyzerInput

    @trace_tool("security_group_analyzer")
    def _run(self, region: str = "us-east-1") -> str:
        ec2 = boto3.client("ec2", region_name=region)
        sgs = ec2.describe_security_groups()
        findings = []

        # Get instances to check which SGs are in use
        instances = ec2.describe_instances()
        used_sgs = set()
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                for sg in instance.get("SecurityGroups", []):
                    used_sgs.add(sg["GroupId"])

        for sg in sgs["SecurityGroups"]:
            sg_id = sg["GroupId"]
            sg_name = sg["GroupName"]

            # Check 1: Default SG with rules (should have no custom rules)
            if sg_name == "default":
                if sg["IpPermissions"] or sg["IpPermissionsEgress"]:
                    ingress_count = len(sg["IpPermissions"])
                    findings.append({
                        "resource_id": sg_id,
                        "resource_name": sg_name,
                        "issue": "Default security group has custom rules",
                        "severity": "HIGH",
                        "detail": f"Default SG has {ingress_count} ingress rules. Best practice: default SG should have NO rules.",
                        "current": f"{ingress_count} ingress rules present",
                        "expected": "No ingress or egress rules on default SG",
                    })

            # Check 2: Launch-wizard SGs (stale, auto-created)
            if "launch-wizard" in sg_name:
                in_use = sg_id in used_sgs
                findings.append({
                    "resource_id": sg_id,
                    "resource_name": sg_name,
                    "issue": "Stale launch-wizard security group exists",
                    "severity": "MEDIUM" if not in_use else "LOW",
                    "detail": f"Auto-created launch-wizard SG. In use: {in_use}. These should be replaced with properly named, scoped SGs.",
                    "current": f"Launch-wizard SG exists (in_use={in_use})",
                    "expected": "Purpose-built security groups with descriptive names",
                })

            # Check 3: Open ingress (0.0.0.0/0) on sensitive ports
            sensitive_ports = {22: "SSH", 3389: "RDP", 3306: "MySQL", 5432: "PostgreSQL", 27017: "MongoDB"}
            for rule in sg["IpPermissions"]:
                from_port = rule.get("FromPort", 0)
                to_port = rule.get("ToPort", 65535)

                for ip_range in rule.get("IpRanges", []):
                    if ip_range.get("CidrIp") == "0.0.0.0/0":
                        # Check if it's a sensitive port
                        for port, service in sensitive_ports.items():
                            if from_port <= port <= to_port:
                                findings.append({
                                    "resource_id": sg_id,
                                    "resource_name": sg_name,
                                    "issue": f"Port {port} ({service}) open to the internet",
                                    "severity": "CRITICAL",
                                    "detail": f"Ingress rule allows 0.0.0.0/0 on port {port} ({service}). This exposes the service to the entire internet.",
                                    "current": f"0.0.0.0/0 on port {port}",
                                    "expected": "Restrict to specific IP ranges or use VPN/bastion",
                                })

                        # Check for wide port range open to internet
                        port_range = to_port - from_port
                        if port_range > 100:
                            findings.append({
                                "resource_id": sg_id,
                                "resource_name": sg_name,
                                "issue": f"Wide port range ({from_port}-{to_port}) open to internet",
                                "severity": "CRITICAL",
                                "detail": f"Ingress allows 0.0.0.0/0 on ports {from_port}-{to_port}. This is extremely permissive.",
                                "current": f"0.0.0.0/0 on ports {from_port}-{to_port}",
                                "expected": "Restrict to minimum required ports",
                            })

        return json.dumps({
            "total_security_groups": len(sgs["SecurityGroups"]),
            "findings_count": len(findings),
            "findings": findings,
        }, indent=2)
