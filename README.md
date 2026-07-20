# 🛡️ AWS Security Posture Agent

A multi-agent AI system that scans your AWS account for security misconfigurations, scores risk, and generates actionable remediation plans — fully instrumented with **Sentry AI Agent Monitoring**.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![CrewAI](https://img.shields.io/badge/crewai-1.15-green)
![Sentry](https://img.shields.io/badge/sentry-AI%20Monitoring-purple)
![Bedrock](https://img.shields.io/badge/AWS-Bedrock%20Nova%20Pro-orange)

## Architecture

```
Transaction: "Security Posture Scan"
├── gen_ai.invoke_agent: ResourceDiscovery (17s)
│   └── gen_ai.execute_tool: aws_resource_scanner
├── gen_ai.invoke_agent: SecurityScanner (18s)
│   ├── gen_ai.execute_tool: security_group_analyzer
│   ├── gen_ai.execute_tool: s3_config_checker
│   ├── gen_ai.execute_tool: iam_analyzer
│   ├── gen_ai.execute_tool: ec2_security_checker
│   └── gen_ai.execute_tool: lambda_security_checker
├── gen_ai.invoke_agent: ComplianceChecker (6s)
├── gen_ai.invoke_agent: RiskScorer (4s)
└── gen_ai.invoke_agent: RemediationPlanner (10s)
```

## 5 Specialist Agents

| # | Agent | Role | Tools |
|---|-------|------|-------|
| 1 | **ResourceDiscovery** | AWS Infrastructure Cartographer | `aws_resource_scanner` |
| 2 | **SecurityScanner** | Cloud Security Analyst | `security_group_analyzer`, `s3_config_checker`, `iam_analyzer`, `ec2_security_checker`, `lambda_security_checker` |
| 3 | **ComplianceChecker** | Compliance & Governance Specialist | — (analyzes upstream findings) |
| 4 | **RiskScorer** | Risk Quantification Analyst | — (scores findings) |
| 5 | **RemediationPlanner** | Security Remediation Architect | — (generates fix commands) |

## What It Checks

- **Security Groups**: Open ports (SSH, RDP, DB), wide ranges, default SG rules, stale launch-wizard groups
- **S3 Buckets**: Encryption, versioning, public access blocks
- **IAM Roles**: AdministratorAccess, PowerUserAccess, overly permissive policies
- **IAM Users**: MFA enabled, access key age, direct policy attachments
- **EC2 Instances**: Missing IAM instance profiles, unencrypted EBS volumes, public IPs on internal instances, default SG usage
- **Lambda Functions**: Deprecated runtimes, overly permissive execution roles, missing dead letter queues, large deployment packages
- Maps findings to **CIS AWS Foundations Benchmark** controls
- Scores each finding: severity (1-10) × blast radius × exploitability

## Quick Start

```bash
# Clone
git clone https://github.com/simplynadaf/aws-security-posture-agent.git
cd security-posture-agent

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Add your SENTRY_DSN and configure AWS credentials

# Run CLI
python -m security_posture.main

# Run Streamlit UI
streamlit run streamlit_app.py
```

## Configuration

```bash
# .env
SENTRY_DSN=https://your-dsn@sentry.io/project
AWS_DEFAULT_REGION=us-east-1
MODEL=bedrock/amazon.nova-pro-v1:0
```

Requires AWS credentials configured via `~/.aws/credentials` or environment variables with permissions to read EC2, S3, IAM, Lambda, API Gateway, DynamoDB, and Security Groups.

## Sentry AI Agent Monitoring

Every pipeline run sends a full trace to Sentry with:
- `gen_ai.invoke_agent` spans for each of 5 agents
- `gen_ai.execute_tool` spans for each of 5 boto3 tool executions
- Token usage attribution per agent
- Duration and output size metrics
- Error capture with full stack traces

## Performance Bug Fix

**Problem**: The `IAMAnalyzer` tool fetched all 90 IAM roles without pagination, producing 27KB of JSON that overwhelmed the LLM context window.

**Fix** (see [PR #1](https://github.com/simplynadaf/aws-security-posture-agent/pull/1)):
1. Paginate to top 20 most-recently-used roles
2. Skip service-linked roles (31 roles, can't modify anyway)
3. Sort by last-used date for relevance
4. Token budget guard: truncate output if >4000 chars

**Result**: IAM tool output reduced 42%, SecurityScanner agent 21% faster (best run), 66% fewer API calls.

See `docs/METRICS-COMPARISON.md` for full before/after data.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent Framework | CrewAI 1.15 |
| LLM | Amazon Bedrock Nova Pro v1 |
| Monitoring | Sentry SDK 2.65 (AI Agent Monitoring) |
| Cloud SDK | boto3 |
| UI | Streamlit |
| Language | Python 3.12 |

## License

MIT
