"""Sentry AI Agent Monitoring integration for the Security Posture pipeline.

Provides:
- init_sentry(): Initialize Sentry with full tracing
- SentryInstrumentedCrew: Crew subclass that wraps each task in gen_ai.invoke_agent spans
- trace_tool(): Decorator for tool _run methods to create gen_ai.execute_tool spans
"""
import json
import os
import time
import functools
from contextlib import contextmanager

import sentry_sdk
from sentry_sdk import start_span


def init_sentry(dsn: str = None):
    """Initialize Sentry with AI Agent Monitoring enabled."""
    dsn = dsn or os.getenv("SENTRY_DSN", "")

    if not dsn:
        print("⚠️  WARNING: No SENTRY_DSN configured. Monitoring disabled.")
        return False

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        enable_tracing=True,
        environment="development",
        release="security-posture-agent@1.0.0",
        send_default_pii=False,
    )
    print("✅ Sentry initialized with AI Agent Monitoring.")
    return True


@contextmanager
def agent_span(agent_name: str, model: str = "amazon.nova-pro-v1:0"):
    """Context manager that creates a gen_ai.invoke_agent span."""
    with start_span(
        op="gen_ai.invoke_agent",
        name=f"invoke_agent {agent_name}",
    ) as span:
        span.set_data("gen_ai.operation.name", "invoke_agent")
        span.set_data("gen_ai.agent.name", agent_name)
        span.set_data("gen_ai.request.model", model)
        span.set_data("gen_ai.pipeline.name", "security-posture-scan")

        start_time = time.time()
        yield span
        elapsed = time.time() - start_time

        span.set_data("duration_seconds", round(elapsed, 2))


def trace_tool(tool_name: str):
    """Decorator to wrap a tool's _run method with a gen_ai.execute_tool span.
    
    Usage:
        @trace_tool("aws_resource_scanner")
        def _run(self, region: str = "us-east-1") -> str:
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with start_span(
                op="gen_ai.execute_tool",
                name=f"execute_tool {tool_name}",
            ) as span:
                span.set_data("gen_ai.operation.name", "execute_tool")
                span.set_data("gen_ai.tool.name", tool_name)

                # Capture input args (safely truncated)
                try:
                    safe_kwargs = {k: str(v)[:200] for k, v in kwargs.items()}
                    span.set_data("gen_ai.tool.call.arguments", json.dumps(safe_kwargs))
                except Exception:
                    pass

                start_time = time.time()
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time

                # Capture result size and summary
                span.set_data("duration_seconds", round(elapsed, 2))
                if isinstance(result, str):
                    span.set_data("result_length_chars", len(result))
                    # Parse JSON to get counts if possible
                    try:
                        data = json.loads(result)
                        if "findings_count" in data:
                            span.set_data("findings_count", data["findings_count"])
                        if "total_resources" in data:
                            span.set_data("total_resources", data["total_resources"])
                        if "total_roles_analyzed" in data:
                            span.set_data("total_roles_analyzed", data["total_roles_analyzed"])
                    except (json.JSONDecodeError, KeyError):
                        pass

                return result
        return wrapper
    return decorator


# Map task names to agent display names (for Sentry spans)
TASK_AGENT_MAP = {
    "resource_discovery_task": "ResourceDiscovery",
    "security_scanning_task": "SecurityScanner",
    "compliance_check_task": "ComplianceChecker",
    "risk_scoring_task": "RiskScorer",
    "remediation_planning_task": "RemediationPlanner",
}
