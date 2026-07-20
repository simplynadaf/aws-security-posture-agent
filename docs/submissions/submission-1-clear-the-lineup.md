---
title: "Sentry's AI Agent Monitoring Caught a Token Explosion in My 5-Agent AWS Security Scanner"
published: true
description: "One tool burned 3x the tokens it should. Sentry agent tracing found it. Fix: pagination + token budget guard. 42% smaller output, 21% faster."
tags: devchallenge, bugsmash, ai, aws
cover_image: [COVER_IMAGE_URL]
---

*This is a submission for [DEV's Summer Bug Smash: Clear the Lineup](https://dev.to/bugsmash) powered by [Sentry](https://sentry.io/).*

## Project Overview

I built an **AWS Security Posture Agent**: five specialist AI agents that scan your AWS account for security misconfigurations, map findings to CIS benchmarks, score risk, and generate copy-paste fix commands.

The agents run sequentially on CrewAI with Amazon Bedrock Nova Pro as the LLM:

```
1. ResourceDiscovery    → inventories EC2, S3, Lambda, IAM, SGs, API GW, DynamoDB
2. SecurityScanner      → finds open ports, public buckets, admin roles, insecure configs
3. ComplianceChecker    → maps to CIS AWS Foundations Benchmark
4. RiskScorer           → severity × blast radius × exploitability
5. RemediationPlanner   → generates AWS CLI fix commands
```

Each agent has custom boto3 tools that make real AWS API calls against a live account with 90 IAM roles, 14 S3 buckets, 9 security groups, and 7 Lambda functions. Not test data. Real findings.

{% github https://github.com/simplynadaf/aws-security-posture-agent %}

### Demo

Here's the full scan running against my AWS account. The scan portion is sped up 4x, results walkthrough is at normal speed:

{% youtube YOUR_YOUTUBE_VIDEO_ID %}

## Bug Fix or Performance Improvement

The **SecurityScanner agent** was taking 22.6 seconds while every other agent averaged 5-10 seconds. Without visibility into what was happening inside each agent's execution, I would have blamed Bedrock latency and moved on.

The root cause: my `IAMAnalyzer` tool was fetching all 90 IAM roles from the account (59 after filtering service-linked roles), serializing them into a 27KB JSON blob, and handing that entire payload to the LLM as tool output. The context window got overwhelmed. CrewAI's internal retry logic kicked in, burning tokens on a second attempt with even more context.

One tool. Wrong default. The entire pipeline suffered.

## Code

PR with the fix:

{% github https://github.com/simplynadaf/aws-security-posture-agent/pull/1 %}

The core change lives in `src/security_posture/tools/iam_analyzer.py`. Here's the before and after:

**Before (the bug):**

```python
# Fetches ALL roles without pagination limit
roles = iam.list_roles(MaxItems=100)
role_details = []

for role in roles["Roles"]:
    role_name = role["RoleName"]
    if role.get("Path", "").startswith("/aws-service-role/"):
        continue
    # Analyzes every single role...
    attached = iam.list_attached_role_policies(RoleName=role_name)
    # ...builds massive JSON output
```

This produces 26,980 characters of JSON for an account with 90 roles. The LLM chokes on it.

**After (the fix):**

```python
# FIX: Paginate and sort by relevance
all_roles = []
paginator = iam.get_paginator("list_roles")
for page in paginator.paginate():
    all_roles.extend(page["Roles"])

# Filter service-linked roles (31 roles, can't modify anyway)
auditable_roles = [
    r for r in all_roles
    if not r.get("Path", "").startswith("/aws-service-role/")
]

# Sort by last used date (most active first)
auditable_roles.sort(key=_last_used_sort_key, reverse=True)

# Take only top 20 roles
roles_to_analyze = auditable_roles[:max_roles]
```

Plus a token budget guard at the end:

```python
# Token budget guard: truncate if output exceeds threshold
if len(output) > 4000:
    result["role_summary"] = [
        {"role_name": r["role_name"], "policies": r.get("attached_policies", [])}
        for r in role_details
    ]
    result["note"] = "Role details truncated to stay within token budget"
    output = json.dumps(result, indent=2, default=str)
```

Three changes. Pagination, relevance sorting, and a safety valve. The SecurityScanner stopped retrying.

## My Improvements

The fix itself is simple. The interesting part is how I found it.

Without Sentry's trace waterfall, all I would have seen is "pipeline takes 62 seconds." Maybe I'd profile the Python code. Maybe I'd add `time.time()` calls around each agent. But the real problem wasn't Python execution time. It was the LLM getting a context payload it couldn't process cleanly on the first attempt.

The approach:

1. Wrap each agent execution in a `gen_ai.invoke_agent` span
2. Wrap each tool call in a `gen_ai.execute_tool` span  
3. Run the pipeline and look at the trace waterfall
4. The SecurityScanner span was visually obvious: twice the width of everything else
5. Inside it, the `iam_analyzer` tool span showed a `result_length_chars` of 26,980
6. Compare to `security_group_analyzer` at 4,200 chars and `s3_config_checker` at 3,800 chars

The disproportion was the clue. The fix followed naturally: if the tool output is 7x larger than its siblings, reduce it.

**Results:**

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| IAM tool output | 26,980 chars | 15,532 chars | 42% smaller |
| SecurityScanner time | 22.6s | 17.8s | 21% faster |
| IAM API calls | 59 | 20 | 66% fewer |
| Total pipeline | 62.0s | 57.7s | 7% faster |
| Security findings | 97 | 97 | No coverage loss |

The 21% improvement on the SecurityScanner came from the LLM completing analysis in a single pass instead of retrying.

## Best Use of Sentry

I used Sentry's AI Agent Monitoring to instrument a multi-agent CrewAI pipeline from scratch. This isn't a web app or API. It's five autonomous AI agents making LLM calls and executing custom tools. Standard APM wouldn't help here.

### What I instrumented

Every pipeline run creates a Sentry transaction with this span hierarchy:

```
Transaction: "Security Posture Scan" (57s)
├── gen_ai.invoke_agent: ResourceDiscovery
│   └── gen_ai.execute_tool: aws_resource_scanner
├── gen_ai.invoke_agent: SecurityScanner
│   ├── gen_ai.execute_tool: security_group_analyzer
│   ├── gen_ai.execute_tool: s3_config_checker
│   ├── gen_ai.execute_tool: iam_analyzer
│   ├── gen_ai.execute_tool: ec2_security_checker
│   └── gen_ai.execute_tool: lambda_security_checker
├── gen_ai.invoke_agent: ComplianceChecker
├── gen_ai.invoke_agent: RiskScorer
└── gen_ai.invoke_agent: RemediationPlanner
```

### The instrumentation code

For each agent (in `main.py`):

```python
with start_span(
    op="gen_ai.invoke_agent",
    name=f"invoke_agent {agent_name}",
) as agent_span:
    agent_span.set_data("gen_ai.operation.name", "invoke_agent")
    agent_span.set_data("gen_ai.agent.name", agent_name)
    agent_span.set_data("gen_ai.request.model", "amazon.nova-pro-v1:0")
    agent_span.set_data("gen_ai.pipeline.name", "security-posture-scan")

    task_output = task_obj.execute_sync(
        agent=task_obj.agent,
        context=context,
        tools=task_obj.agent.tools,
    )
    
    agent_span.set_data("duration_seconds", round(elapsed, 2))
    agent_span.set_data("output_length_chars", len(str(task_output)))
```

For each tool (decorator in `monitoring.py`):

```python
def trace_tool(tool_name: str):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with start_span(
                op="gen_ai.execute_tool",
                name=f"execute_tool {tool_name}",
            ) as span:
                span.set_data("gen_ai.tool.name", tool_name)
                result = func(*args, **kwargs)
                span.set_data("result_length_chars", len(result))
                try:
                    data = json.loads(result)
                    if "findings_count" in data:
                        span.set_data("findings_count", data["findings_count"])
                except (json.JSONDecodeError, KeyError):
                    pass
                return result
        return wrapper
    return decorator
```

### Sentry features used

| Feature | How I Used It |
|---------|--------------|
| **Distributed Tracing** | Full pipeline trace from start to final report |
| **AI Agent Monitoring** | `gen_ai.invoke_agent` spans for all 5 agents |
| **Tool Execution Tracing** | `gen_ai.execute_tool` spans for all 5 boto3 tools |
| **Custom Span Data** | Token counts, output sizes, duration, finding counts |
| **Error Monitoring** | Exception capture with `sentry_sdk.capture_exception()` |
| **Breadcrumbs** | Agent completion events via task callbacks |
| **Transaction Metadata** | Model name, pipeline config, agent count |

### What Sentry revealed

[SCREENSHOT: Sentry trace waterfall showing SecurityScanner as the longest span - BEFORE fix]

The trace waterfall made the bottleneck visually obvious. The SecurityScanner span was nearly twice the width of any other agent. Inside it, the `iam_analyzer` tool span showed `result_length_chars: 26980` while the other tools showed 3,800-4,200.

[SCREENSHOT: Sentry trace waterfall AFTER fix - all spans proportional]

After the fix, all agent spans are proportional to their actual task complexity. No single agent dominates the trace.

### Why this matters for AI agent observability

Standard logging tells you an agent "finished." It doesn't tell you which tool inside which agent returned a 27KB payload that triggered a retry you never asked for.

With five agents each making their own LLM calls and tool executions, you need span-level visibility. Sentry's `gen_ai.invoke_agent` and `gen_ai.execute_tool` conventions gave me exactly that. I could see the problem in the trace waterfall before I even looked at the code.

That's the difference between "add some logging" and actual AI observability.

---

*Built during DEV's Summer Bug Smash 2026. The agent found 97 real security findings in my AWS account, including open SSH ports, missing MFA, roles with full admin access, unencrypted EBS volumes, and Lambda functions on deprecated runtimes. The fix is in production.*
