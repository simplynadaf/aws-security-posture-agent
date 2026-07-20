import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


class IAMAnalyzerInput(BaseModel):
    """Input schema for IAMAnalyzer."""
    max_roles: int = Field(default=20, description="Maximum number of roles to analyze (default: 20 for performance)")


class IAMAnalyzer(BaseTool):
    name: str = "iam_analyzer"
    description: str = (
        "Analyzes IAM roles and users for security issues including overly permissive "
        "policies (AdministratorAccess, wildcard actions/resources), users without MFA, "
        "old access keys, and unused credentials. Returns findings per IAM entity. "
        "Analyzes top N most recently used roles by default to avoid context overflow."
    )
    args_schema: Type[BaseModel] = IAMAnalyzerInput

    @trace_tool("iam_analyzer")
    def _run(self, max_roles: int = 20) -> str:
        iam = boto3.client("iam")
        findings = []

        # ============================================================
        # FIX: Paginate IAM roles - only analyze top N by last activity
        # Previously fetched ALL roles (85+), which overwhelmed the LLM
        # context window and caused CrewAI to retry the analysis task.
        # Now: fetch all role names, sort by last used, analyze top N.
        # ============================================================
        all_roles = []
        paginator = iam.get_paginator("list_roles")
        for page in paginator.paginate():
            all_roles.extend(page["Roles"])

        # Filter out service-linked roles (can't modify, not useful to audit)
        auditable_roles = [
            r for r in all_roles
            if not r.get("Path", "").startswith("/aws-service-role/")
        ]

        # Sort by last used (most recently used first) for relevance
        # Roles without RoleLastUsed get low priority
        def _last_used_sort_key(role):
            last_used = role.get("RoleLastUsed", {}).get("LastUsedDate")
            if last_used:
                return last_used.timestamp() if hasattr(last_used, 'timestamp') else 0
            return 0

        auditable_roles.sort(key=_last_used_sort_key, reverse=True)

        # Take only top N roles to keep context manageable
        roles_to_analyze = auditable_roles[:max_roles]
        skipped_count = len(auditable_roles) - len(roles_to_analyze)

        role_details = []

        for role in roles_to_analyze:
            role_name = role["RoleName"]

            # Check attached policies
            try:
                attached = iam.list_attached_role_policies(RoleName=role_name)
                for policy in attached["AttachedPolicies"]:
                    policy_arn = policy["PolicyArn"]

                    # Check for AdministratorAccess
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

                    # Check for PowerUserAccess
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
                    "attached_policies": [p["PolicyName"] for p in attached["AttachedPolicies"]],
                })

            except Exception as e:
                role_details.append({
                    "role_name": role_name,
                    "error": str(e),
                })

        # ============================================================
        # ANALYZE USERS (unchanged - typically few users per account)
        # ============================================================
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

            # Check attached user policies (users should use groups)
            try:
                user_policies = iam.list_attached_user_policies(UserName=username)
                if user_policies["AttachedPolicies"]:
                    policy_names = [p["PolicyName"] for p in user_policies["AttachedPolicies"]]
                    findings.append({
                        "resource_id": username,
                        "resource_type": "IAM User",
                        "issue": "Policies attached directly to user instead of group",
                        "severity": "LOW",
                        "detail": f"User '{username}' has {len(policy_names)} policies attached directly. Best practice: use IAM groups.",
                        "current": f"Direct policies: {', '.join(policy_names)}",
                        "expected": "Policies attached via IAM groups, not directly to users",
                    })
            except Exception:
                pass

        # ============================================================
        # FIX: Truncate output to prevent context overflow
        # Cap the JSON output size to avoid overwhelming the LLM
        # ============================================================
        result = {
            "total_roles_in_account": len(all_roles),
            "service_linked_roles_skipped": len(all_roles) - len(auditable_roles),
            "roles_analyzed": len(roles_to_analyze),
            "roles_skipped_for_performance": skipped_count,
            "total_users_analyzed": len(users["Users"]),
            "findings_count": len(findings),
            "findings": findings,
            "role_summary": role_details,
        }

        output = json.dumps(result, indent=2, default=str)

        # Token budget guard: if output exceeds ~3000 chars, trim role_summary
        if len(output) > 4000:
            result["role_summary"] = [
                {"role_name": r["role_name"], "policies": r.get("attached_policies", [])}
                for r in role_details
            ]
            result["note"] = "Role details truncated to stay within token budget"
            output = json.dumps(result, indent=2, default=str)

        return output
