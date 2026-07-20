import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class IAMAnalyzerInput(BaseModel):
    """Input schema for IAMAnalyzer."""
    region: str = Field(default="us-east-1", description="AWS region")


class IAMAnalyzer(BaseTool):
    name: str = "iam_analyzer"
    description: str = (
        "Analyzes IAM roles and users for security issues including overly permissive "
        "policies (AdministratorAccess, wildcard actions/resources), users without MFA, "
        "old access keys, and unused credentials. Returns findings per IAM entity."
    )
    args_schema: Type[BaseModel] = IAMAnalyzerInput

    @trace_tool("iam_analyzer")
    def _run(self, region: str = "us-east-1") -> str:
        iam = boto3.client("iam")
        findings = []

        # BUG: Fetches ALL roles without pagination or limit
        # On accounts with 85+ roles, this produces 27KB+ of JSON output
        # which overwhelms the LLM context window and triggers CrewAI retries
        roles = iam.list_roles(MaxItems=100)
        role_details = []

        for role in roles["Roles"]:
            role_name = role["RoleName"]

            # Skip service-linked roles
            if role.get("Path", "").startswith("/aws-service-role/"):
                continue

            # Check attached policies for every single role
            try:
                attached = iam.list_attached_role_policies(RoleName=role_name)
                for policy in attached["AttachedPolicies"]:
                    policy_arn = policy["PolicyArn"]

                    if "AdministratorAccess" in policy_arn:
                        findings.append({
                            "resource_id": role_name,
                            "resource_type": "IAM Role",
                            "issue": "Role has AdministratorAccess policy attached",
                            "severity": "CRITICAL",
                            "detail": f"Role '{role_name}' has full admin access. This violates least-privilege principle.",
                            "current": f"Attached: {policy_arn}",
                            "expected": "Scoped policies with minimum required permissions",
                        })

                    if "PowerUserAccess" in policy_arn:
                        findings.append({
                            "resource_id": role_name,
                            "resource_type": "IAM Role",
                            "issue": "Role has PowerUserAccess policy attached",
                            "severity": "HIGH",
                            "detail": f"Role '{role_name}' has PowerUserAccess. Nearly as dangerous as full admin.",
                            "current": f"Attached: {policy_arn}",
                            "expected": "Scoped policies with minimum required permissions",
                        })

                role_details.append({
                    "role_name": role_name,
                    "created": str(role["CreateDate"]),
                    "last_used": str(role.get("RoleLastUsed", {}).get("LastUsedDate", "Never")),
                    "attached_policies": [p["PolicyName"] for p in attached["AttachedPolicies"]],
                    "path": role.get("Path", "/"),
                })

            except Exception as e:
                role_details.append({
                    "role_name": role_name,
                    "error": str(e),
                })

        # Analyze users
        users = iam.list_users()

        for user in users["Users"]:
            username = user["UserName"]

            # Check MFA
            try:
                mfa_devices = iam.list_mfa_devices(UserName=username)
                if not mfa_devices["MFADevices"]:
                    findings.append({
                        "resource_id": username,
                        "resource_type": "IAM User",
                        "issue": "IAM user has no MFA device configured",
                        "severity": "CRITICAL",
                        "detail": f"User '{username}' has no MFA. Account compromise via stolen credentials is trivial without MFA.",
                        "current": "No MFA devices",
                        "expected": "At least one MFA device (virtual or hardware)",
                    })
            except Exception:
                pass

            # Check access key age
            try:
                keys = iam.list_access_keys(UserName=username)
                for key in keys["AccessKeyMetadata"]:
                    from datetime import datetime, timezone
                    created = key["CreateDate"]
                    if isinstance(created, str):
                        continue
                    age_days = (datetime.now(timezone.utc) - created).days
                    if age_days > 90:
                        findings.append({
                            "resource_id": username,
                            "resource_type": "IAM User",
                            "issue": f"Access key is {age_days} days old (>90 days)",
                            "severity": "MEDIUM",
                            "detail": f"User '{username}' access key '{key['AccessKeyId']}' is {age_days} days old. Keys should be rotated every 90 days.",
                            "current": f"Key age: {age_days} days",
                            "expected": "Key age < 90 days",
                        })
            except Exception:
                pass

        # BUG: No output size control - dumps everything as massive JSON
        # This can easily exceed 26,000+ characters for 85+ role accounts
        result = {
            "total_roles_in_account": len(roles["Roles"]),
            "total_roles_analyzed": len(role_details),
            "total_users_analyzed": len(users["Users"]),
            "findings_count": len(findings),
            "findings": findings,
            "role_details": role_details,  # Full details for ALL roles - the problem
        }

        return json.dumps(result, indent=2, default=str)
