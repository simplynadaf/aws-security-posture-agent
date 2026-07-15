#!/usr/bin/env python
"""Security Posture Agent - Entry point with Sentry AI Agent Monitoring.

Runs the 5-agent security scanning pipeline with full Sentry instrumentation:
- Transaction: "Security Posture Scan" (wraps entire pipeline)
- Agent spans: gen_ai.invoke_agent for each of 5 agents
- Tool spans: gen_ai.execute_tool for each boto3 tool call (inside tools)
- Token tracking: captures CrewAI token usage metrics
"""
import sys
import os
import time
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

import sentry_sdk
from sentry_sdk import start_span


def run():
    """Run the security posture scan pipeline with full Sentry tracing."""
    from security_posture.monitoring import init_sentry, agent_span, TASK_AGENT_MAP
    from security_posture.crew import SecurityPosture

    # Initialize Sentry
    sentry_enabled = init_sentry()

    print("\n" + "=" * 60)
    print("  🛡️  AWS Security Posture Agent")
    print("  Multi-Agent Security Scanner with AI Observability")
    print("=" * 60 + "\n")

    pipeline_start = time.time()

    # Start a Sentry transaction for the full pipeline
    with sentry_sdk.start_transaction(
        op="security_scan",
        name="Security Posture Scan",
    ) as transaction:
        transaction.set_data("pipeline.agents_count", 5)
        transaction.set_data("pipeline.tools_count", 4)
        transaction.set_data("pipeline.model", "amazon.nova-pro-v1:0")

        try:
            # Build the crew
            posture = SecurityPosture()
            crew_instance = posture.crew()

            # Run the full pipeline - CrewAI handles sequential execution
            # Agent-level spans are created via task execution wrapping
            print("🚀 Starting security scan pipeline...\n")

            # Execute with agent-level span instrumentation
            result = _run_with_agent_spans(crew_instance, transaction)

            pipeline_elapsed = time.time() - pipeline_start

            print("\n" + "=" * 60)
            print("  ✅ SCAN COMPLETE")
            print(f"  ⏱️  Total time: {pipeline_elapsed:.1f}s")
            print("=" * 60 + "\n")

            # Record final metrics
            transaction.set_status("ok")
            transaction.set_data("pipeline.duration_seconds", round(pipeline_elapsed, 2))

            # Capture token usage from CrewAI
            if crew_instance.usage_metrics:
                metrics = crew_instance.usage_metrics
                transaction.set_data("gen_ai.usage.total_tokens",
                    getattr(metrics, 'total_tokens', 0))
                transaction.set_data("gen_ai.usage.prompt_tokens",
                    getattr(metrics, 'prompt_tokens', 0))
                transaction.set_data("gen_ai.usage.completion_tokens",
                    getattr(metrics, 'completion_tokens', 0))
                transaction.set_data("gen_ai.usage.successful_requests",
                    getattr(metrics, 'successful_requests', 0))

                print(f"📊 Token Usage:")
                print(f"   Input tokens:  {getattr(metrics, 'prompt_tokens', 'N/A')}")
                print(f"   Output tokens: {getattr(metrics, 'completion_tokens', 'N/A')}")
                print(f"   Total tokens:  {getattr(metrics, 'total_tokens', 'N/A')}")
                print(f"   LLM calls:     {getattr(metrics, 'successful_requests', 'N/A')}")

            # Flush to ensure all spans are sent
            sentry_sdk.flush(timeout=10)
            print("\n📡 Sentry traces flushed successfully.")

            return result

        except Exception as e:
            transaction.set_status("internal_error")
            sentry_sdk.capture_exception(e)
            sentry_sdk.flush(timeout=10)
            print(f"\n❌ Pipeline failed: {e}")
            raise


def _run_with_agent_spans(crew_instance, transaction):
    """Execute crew tasks with Sentry agent-level spans wrapping each task.
    
    This creates the trace waterfall:
      Transaction: Security Posture Scan
      ├── gen_ai.invoke_agent: ResourceDiscovery
      │   └── gen_ai.execute_tool: aws_resource_scanner
      ├── gen_ai.invoke_agent: SecurityScanner
      │   ├── gen_ai.execute_tool: security_group_analyzer
      │   ├── gen_ai.execute_tool: s3_config_checker
      │   └── gen_ai.execute_tool: iam_analyzer
      ├── gen_ai.invoke_agent: ComplianceChecker
      ├── gen_ai.invoke_agent: RiskScorer
      └── gen_ai.invoke_agent: RemediationPlanner
    """
    from security_posture.monitoring import TASK_AGENT_MAP

    tasks = crew_instance.tasks
    agents = crew_instance.agents
    task_outputs = []

    for i, task_obj in enumerate(tasks):
        # Determine agent name from task
        task_name = _get_task_name(task_obj, i)
        agent_name = TASK_AGENT_MAP.get(task_name, f"Agent_{i+1}")

        print(f"{'─' * 40}")
        print(f"🤖 Agent: {agent_name}")
        print(f"{'─' * 40}")

        # Wrap task execution in a gen_ai.invoke_agent span
        with start_span(
            op="gen_ai.invoke_agent",
            name=f"invoke_agent {agent_name}",
        ) as agent_span:
            agent_span.set_data("gen_ai.operation.name", "invoke_agent")
            agent_span.set_data("gen_ai.agent.name", agent_name)
            agent_span.set_data("gen_ai.request.model", "amazon.nova-pro-v1:0")
            agent_span.set_data("gen_ai.pipeline.name", "security-posture-scan")
            agent_span.set_data("task_index", i)

            task_start = time.time()

            # Execute the task via CrewAI's internal mechanism
            task_output = task_obj.execute_sync(
                agent=task_obj.agent,
                context="\n\n".join(str(o) for o in task_outputs) if task_outputs else "",
                tools=task_obj.agent.tools if task_obj.agent else [],
            )

            task_elapsed = time.time() - task_start
            task_outputs.append(task_output)

            # Record span data
            agent_span.set_data("duration_seconds", round(task_elapsed, 2))
            output_str = str(task_output) if task_output else ""
            agent_span.set_data("output_length_chars", len(output_str))

            # Try to get token usage for this specific task
            if hasattr(task_output, 'token_usage') and task_output.token_usage:
                usage = task_output.token_usage
                agent_span.set_data("gen_ai.usage.input_tokens",
                    getattr(usage, 'prompt_tokens', 0))
                agent_span.set_data("gen_ai.usage.output_tokens",
                    getattr(usage, 'completion_tokens', 0))
                agent_span.set_data("gen_ai.usage.total_tokens",
                    getattr(usage, 'total_tokens', 0))

            print(f"  ✅ Done in {task_elapsed:.1f}s (output: {len(output_str)} chars)\n")

    # Handle output file writing for the last task
    if tasks and hasattr(tasks[-1], 'output_file') and tasks[-1].output_file and task_outputs:
        with open(tasks[-1].output_file, 'w') as f:
            f.write(str(task_outputs[-1]))

    # Create a CrewOutput-like result
    return task_outputs[-1] if task_outputs else None


def _get_task_name(task_obj, index: int) -> str:
    """Extract the task name from a Task object."""
    # CrewAI tasks created with @task decorator store config
    if hasattr(task_obj, 'name') and task_obj.name:
        return task_obj.name
    if hasattr(task_obj, 'description') and task_obj.description:
        desc = task_obj.description.lower()
        if "discovery" in desc or "inventory" in desc:
            return "resource_discovery_task"
        elif "security" in desc and "scan" in desc:
            return "security_scanning_task"
        elif "compliance" in desc:
            return "compliance_check_task"
        elif "risk" in desc or "score" in desc:
            return "risk_scoring_task"
        elif "remediation" in desc or "fix" in desc:
            return "remediation_planning_task"
    # Fallback to index-based mapping
    task_names = list(TASK_AGENT_MAP.keys())
    if index < len(task_names):
        return task_names[index]
    return f"task_{index}"


if __name__ == "__main__":
    run()
