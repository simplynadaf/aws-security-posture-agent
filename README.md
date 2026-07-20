# AWS Security Posture Agent

A multi-agent AI system that scans your AWS account for security misconfigurations, scores risk against CIS benchmarks, and generates copy-paste remediation commands. Five specialist agents. Five custom boto3 tools. Full Sentry AI Agent Monitoring.

[![Python](https://img.shields.io/badge/python-3.12+-blue?style=flat-square)](https://python.org)
[![CrewAI](https://img.shields.io/badge/crewai-1.15-green?style=flat-square)](https://crewai.com)
[![Sentry](https://img.shields.io/badge/sentry-AI%20Agent%20Monitoring-purple?style=flat-square)](https://sentry.io)
[![Bedrock](https://img.shields.io/badge/AWS-Bedrock%20Nova%20Pro-orange?style=flat-square)](https://aws.amazon.com/bedrock/)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

![Landing Page](assets/01-landing.png)

## What It Does

Scans a live AWS account and produces:
- 97 security findings across 5 categories
- CIS AWS Foundations Benchmark mapping for each finding
- Risk scores (severity x blast radius x exploitability)
- Prioritized remediation plan with AWS CLI commands
- Overall posture score (0-100)

Runs against real infrastructure. Not test data, not mock responses. Real findings on real resources.

## Screenshots

### Scan Results (Posture Score + Findings by Severity)
![Results](assets/02-results.png)

### Agent Execution Times
![Agent Times](assets/03-agent-times.png)

### Security Findings Detail
![Findings](assets/04-findings.png)

### Remediation Plan (Copy-Paste CLI Commands)
![Remediation](assets/05-remediation.png)

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
| 1 | ResourceDiscovery | AWS Infrastructure Cartographer | `aws_resource_scanner` |
| 2 | SecurityScanner | Cloud Security Analyst | `security_group_analyzer`, `s3_config_checker`, `iam_analyzer`, `ec2_security_checker`, `lambda_security_checker` |
| 3 | ComplianceChecker | Compliance and Governance Specialist | Analyzes upstream findings |
| 4 | RiskScorer | Risk Quantification Analyst | Scores findings |
| 5 | RemediationPlanner | Security Remediation Architect | Generates fix commands |

## What It Checks

| Category | Checks |
|----------|--------|
| Security Groups | Open ports (SSH, RDP, DB), wide ranges, default SG rules, stale launch-wizard groups |
| S3 Buckets | Default encryption, versioning, public access blocks |
| IAM Roles | AdministratorAccess, PowerUserAccess, wildcard permissions |
| IAM Users | MFA enabled, access key age, direct policy attachments |
| EC2 Instances | Missing IAM profiles, unencrypted EBS, public IPs on internal instances |
| Lambda Functions | Deprecated runtimes, overly permissive roles, missing DLQ |

## Quick Start

```bash
git clone https://github.com/simplynadaf/aws-security-posture-agent.git
cd aws-security-posture-agent

python -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# Add your SENTRY_DSN and configure AWS credentials

# Run via CLI
python -m security_posture.main

# Run via Streamlit UI
streamlit run streamlit_app.py
```

## Configuration

```bash
# .env
SENTRY_DSN=https://your-dsn@sentry.io/project
AWS_DEFAULT_REGION=us-east-1
MODEL=bedrock/amazon.nova-pro-v1:0
```

**Required AWS permissions:** Read access to EC2, S3, IAM, Lambda, API Gateway, DynamoDB, and Security Groups. No write permissions needed.

## Sentry AI Agent Monitoring

Every pipeline run sends a full trace to Sentry:

- `gen_ai.invoke_agent` spans for each of 5 agents
- `gen_ai.execute_tool` spans for each of 5 boto3 tool executions
- Token usage attribution per agent
- Duration and output size metrics
- Error capture with full stack traces
- Task completion breadcrumbs

## Performance Bug Fix

**Problem:** The `IAMAnalyzer` tool fetched all 90 roles without pagination. This produced 27KB of JSON that overwhelmed the LLM context window, causing CrewAI to retry.

**Fix:** [PR #1](https://github.com/simplynadaf/aws-security-posture-agent/pull/1)

1. Paginate to top 20 most-recently-used roles
2. Skip service-linked roles (31 roles, not modifiable anyway)
3. Sort by last-used date for relevance
4. Token budget guard: truncate if output exceeds 4000 chars

**Results:**

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| IAM tool output | 26,980 chars | 15,532 chars | 42% smaller |
| SecurityScanner time | 22.6s | 17.8s | 21% faster |
| IAM API calls | 59 | 20 | 66% fewer |
| Total pipeline | 62.0s | 57.7s | 7% faster |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent Framework | CrewAI 1.15 |
| LLM | Amazon Bedrock Nova Pro v1 |
| Monitoring | Sentry SDK 2.65 (AI Agent Monitoring) |
| Cloud SDK | boto3 |
| UI | Streamlit |
| Language | Python 3.12 |

## Project Structure

```
security-posture-agent/
├── src/security_posture/
│   ├── main.py              # Entry point + Sentry transaction
│   ├── crew.py              # 5-agent crew orchestration
│   ├── monitoring.py        # Sentry AI monitoring helpers
│   ├── config/
│   │   ├── agents.yaml      # Agent definitions
│   │   └── tasks.yaml       # Task definitions
│   └── tools/
│       ├── aws_resource_scanner.py
│       ├── security_group_analyzer.py
│       ├── s3_config_checker.py
│       ├── iam_analyzer.py
│       ├── ec2_security_checker.py
│       └── lambda_security_checker.py
├── streamlit_app.py         # Web dashboard
├── pyproject.toml
└── .env.example
```

## Author

**Sarvar Nadaf**
Cloud Architect | 10+ years in Cloud and IT | 7x AWS Certified | AWS Community Builder

- Website: [sarvarnadaf.com](https://sarvarnadaf.com)
- LinkedIn: [linkedin.com/in/sarvar04](https://www.linkedin.com/in/sarvar04/)
- Dev.to: [dev.to/sarvar_04](https://dev.to/sarvar_04)

## License

MIT
