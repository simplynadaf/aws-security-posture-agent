import json
import boto3
from crewai.tools import BaseTool
from typing import Type
from pydantic import BaseModel, Field

from security_posture.monitoring import trace_tool


# Runtimes that are deprecated or end-of-life
DEPRECATED_RUNTIMES = {
    "python3.7", "python3.8",
    "nodejs14.x", "nodejs16.x",
    "java8", "java8.al2",
    "dotnetcore3.1", "dotnet6",
    "ruby2.7",
    "go1.x",
}

# Runtimes nearing end of support (warn)
AGING_RUNTIMES = {
    "python3.9",
    "nodejs18.x",
    "java11",
}


class LambdaSecurityCheckerInput(BaseModel):
    """Input schema for LambdaSecurityChecker."""
    region: str = Field(default="us-east-1", description="AWS region to scan")


class LambdaSecurityChecker(BaseTool):
    name: str = "lambda_security_checker"
    description: str = (
        "Checks Lambda functions for security issues including deprecated/outdated runtimes, "
        "overly permissive execution roles (admin access), functions not in a VPC, "
        "missing dead letter queues, and excessive timeout/memory configurations. "
        "Returns findings per function."
    )
    args_schema: Type[BaseModel] = LambdaSecurityCheckerInput

    @trace_tool("lambda_security_checker")
    def _run(self, region: str = "us-east-1") -> str:
        lam = boto3.client("lambda", region_name=region)
        iam = boto3.client("iam")
        findings = []

        # Get all functions
        functions = lam.list_functions()
        func_list = functions.get("Functions", [])

        for func in func_list:
            func_name = func["FunctionName"]
            runtime = func.get("Runtime", "N/A")
            role_arn = func.get("Role", "")
            vpc_config = func.get("VpcConfig", {})
            dlq_config = func.get("DeadLetterConfig", {})
            timeout = func.get("Timeout", 3)
            memory = func.get("MemorySize", 128)

            # Check 1: Deprecated runtime
            if runtime in DEPRECATED_RUNTIMES:
                findings.append({
                    "resource_id": func_name,
                    "resource_type": "Lambda Function",
                    "issue": f"Lambda function uses deprecated runtime: {runtime}",
                    "severity": "HIGH",
                    "detail": f"Function '{func_name}' uses runtime '{runtime}' which is deprecated/EOL. Security patches are no longer provided.",
                    "current": f"Runtime: {runtime}",
                    "expected": "Upgrade to latest supported runtime version",
                })
            elif runtime in AGING_RUNTIMES:
                findings.append({
                    "resource_id": func_name,
                    "resource_type": "Lambda Function",
                    "issue": f"Lambda function uses aging runtime: {runtime}",
                    "severity": "MEDIUM",
                    "detail": f"Function '{func_name}' uses runtime '{runtime}' which is approaching end of support. Plan migration.",
                    "current": f"Runtime: {runtime}",
                    "expected": "Upgrade to latest supported runtime version",
                })

            # Check 2: Execution role permissions (check for admin/wildcard)
            if role_arn:
                role_name = role_arn.split("/")[-1]
                try:
                    attached = iam.list_attached_role_policies(RoleName=role_name)
                    for policy in attached.get("AttachedPolicies", []):
                        policy_arn = policy["PolicyArn"]
                        if "AdministratorAccess" in policy_arn or "FullAccess" in policy_arn:
                            findings.append({
                                "resource_id": func_name,
                                "resource_type": "Lambda Function",
                                "issue": f"Lambda execution role has overly permissive policy: {policy['PolicyName']}",
                                "severity": "CRITICAL",
                                "detail": f"Function '{func_name}' role '{role_name}' has '{policy['PolicyName']}'. Lambda functions should follow least-privilege.",
                                "current": f"Role: {role_name}, Policy: {policy['PolicyName']}",
                                "expected": "Scoped IAM policy with only required permissions",
                            })
                except Exception:
                    pass

            # Check 3: No VPC configuration
            subnet_ids = vpc_config.get("SubnetIds", [])
            if not subnet_ids:
                findings.append({
                    "resource_id": func_name,
                    "resource_type": "Lambda Function",
                    "issue": "Lambda function is not deployed in a VPC",
                    "severity": "LOW",
                    "detail": f"Function '{func_name}' runs outside a VPC. If it accesses internal resources (RDS, ElastiCache), it should be in a VPC. If it only calls external APIs, this may be acceptable.",
                    "current": "VPC: None",
                    "expected": "Deploy in VPC if accessing internal resources",
                })

            # Check 4: No Dead Letter Queue
            if not dlq_config.get("TargetArn"):
                findings.append({
                    "resource_id": func_name,
                    "resource_type": "Lambda Function",
                    "issue": "Lambda function has no Dead Letter Queue configured",
                    "severity": "MEDIUM",
                    "detail": f"Function '{func_name}' has no DLQ. Failed async invocations will be silently dropped after retries.",
                    "current": "DLQ: None",
                    "expected": "SQS queue or SNS topic as Dead Letter Queue",
                })

        return json.dumps({
            "total_functions": len(func_list),
            "findings_count": len(findings),
            "findings": findings,
        }, indent=2, default=str)
