---
title: "4 Silent Failures, 2 Undocumented APIs, and a Container That Crashed Because of a Missing User Directive"
published: true
description: "What happened when I tried to deploy a CrewAI agent to AWS Bedrock AgentCore. Every error was a 200 OK. Every fix took hours to find. Here's the full debugging trail."
tags: devchallenge, bugsmash, ai, aws
cover_image: [COVER_IMAGE_URL]
---

*This is a submission for [DEV's Summer Bug Smash: Smash Stories](https://dev.to/bugsmash) powered by [Sentry](https://sentry.io/).*

I spent a week deploying a CrewAI agent to AWS Bedrock AgentCore. The SDK wasn't on PyPI. The error messages were 200 OKs. The container crashed without logs. And the naming regex rejected hyphens without telling me why.

This is the full debugging trail. Every failure was silent. Every fix required reading source code nobody documented.

## Table of Contents

* [The Project](#the-project)
* [Failure 1: The SDK That Doesn't Exist on PyPI](#failure-1-the-sdk-that-doesnt-exist-on-pypi)
* [Failure 2: The 200 OK That Means Failure](#failure-2-the-200-ok-that-means-failure)
* [Failure 3: The Container That Crashed With No Logs](#failure-3-the-container-that-crashed-with-no-logs)
* [Failure 4: The Naming Regex Nobody Documented](#failure-4-the-naming-regex-nobody-documented)
* [The Two-Client Split Nobody Mentions](#the-two-client-split-nobody-mentions)
* [What I Learned](#what-i-learned)

## The project

I built a resume-tailoring AI agent with CrewAI and Amazon Bedrock. It takes a job description, analyzes your resume, identifies gaps, and rewrites bullet points to match what the role actually needs.

Locally it worked perfectly. CrewAI orchestrates the agents, Bedrock Nova Pro handles the LLM calls, and the output is solid. Deploying it to production was the problem.

AWS launched Bedrock AgentCore in June 2026 as a managed runtime for AI agents. You containerize your agent, push the image, and AgentCore handles scaling, memory, and invocation. Sounds simple.

It was not simple.

## Failure 1: The SDK that doesn't exist on PyPI

The docs say to install `bedrock-agentcore-client`. I ran:

```bash
pip install bedrock-agentcore-client
```

It installed successfully. No errors. That's because there's a **placeholder package** on PyPI with that name. It installs, imports fail silently, and your container builds successfully with a broken dependency inside.

The real SDK lives in AWS's CodeArtifact registry. You need to configure pip to pull from a private index:

```bash
aws codeartifact login --tool pip \
  --domain amazon-agent-runtimes \
  --repository agent-runtimes-pypi \
  --domain-owner 600427722194
```

Then install from there. The PyPI package is a trap. Nobody warns you.

**Hours lost: 3.** The error only appears at runtime when the container tries to import the module. The build succeeds. The push succeeds. The deployment succeeds. The invocation returns an empty payload.

## Failure 2: The 200 OK that means failure

After fixing the SDK, I deployed and invoked the agent:

```bash
aws bedrock-agentcore-control invoke-agent-runtime \
  --agent-runtime-id abc123 \
  --payload '{"job_description": "..."}'
```

Response: HTTP 200. Payload: empty string.

Not a 500. Not a 400. Not an error message. A successful HTTP response with nothing inside.

I checked CloudWatch. No logs. I checked the container status. Running. I checked the agent runtime status. Active.

The problem: my IAM role was missing `bedrock:GetAgentRuntime` permission. Without it, the invocation endpoint accepts the request, routes it nowhere, and returns a 200 with an empty body.

There is no error message. There is no log entry. The service returns success when it fails.

**Hours lost: 5.** I tried different payloads, different content types, different SDK versions, curl vs boto3, synchronous vs streaming. All 200 OK, all empty. The fix was one IAM permission that produces zero error signal when missing.

```json
{
  "Effect": "Allow",
  "Action": "bedrock:GetAgentRuntime",
  "Resource": "*"
}
```

## Failure 3: The container that crashed with no logs

Next failure. Container starts, passes health checks for 30 seconds, then dies. No exception in CloudWatch. No crash log. Status shows "Failed" with no reason.

I added every logging statement I could think of. Print statements. Structured logging. Exception handlers wrapping every import. Nothing appeared in CloudWatch because the container never got far enough to initialize the logging framework.

The cause: missing `USER 1000` directive in the Dockerfile.

```dockerfile
# This crashes silently
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -e .
CMD ["python", "-m", "my_agent"]
```

```dockerfile
# This works
FROM python:3.12-slim
RUN useradd -m -u 1000 agentuser
WORKDIR /app
COPY . .
RUN pip install -e .
USER 1000
CMD ["python", "-m", "my_agent"]
```

AgentCore requires the container to run as UID 1000. If it doesn't, the runtime kills the container. The error message in the console says "Failed." Just "Failed." No mention of user directives, permissions, or UID requirements.

I found this by reading the AgentCore team's GitHub sample repos. Not the docs. The sample Dockerfile.

**Hours lost: 4.**

## Failure 4: The naming regex nobody documented

I wanted to name my agent runtime `resume-tailor-agent`. Deployment failed:

```
An error occurred (ValidationException): 
  Name must match pattern: ^[a-zA-Z0-9_]+$
```

No hyphens allowed. Fine. I renamed to `resume_tailor_agent` and moved on.

But the error message only appears if you use the control plane client. If you use the console, it just... doesn't submit. No red border, no error toast, no validation message. The button does nothing.

**Hours lost: 1.** Small one, but the pattern: silent failures.

## The two-client split nobody mentions

Here's where it gets architectural. AgentCore has TWO Python clients:

1. `bedrock-agentcore-control` for managing runtimes (create, update, delete)
2. `bedrock-agentcore` for the runtime SDK (what runs inside your container)

The documentation uses both interchangeably. Code samples import from one in the setup section and the other in the invocation section. They have different install paths, different CodeArtifact repositories, and different API surfaces.

If you install the wrong one, nothing tells you. Your code runs until it hits an import that doesn't exist in the package you installed. And since both packages have overlapping module names in some versions, the error might be an `AttributeError` deep in a function call, not a clean `ImportError` at the top.

I mapped out which client does what:

| Client | Purpose | Install From |
|--------|---------|-------------|
| `bedrock-agentcore-control` | Create/manage runtimes | CodeArtifact (domain: amazon-agent-runtimes) |
| `bedrock-agentcore` | Runtime SDK (inside container) | CodeArtifact (same domain) |
| `boto3` (bedrock-agent) | Invoke from outside | Standard pip |

This table doesn't exist in any documentation I found.

## What I learned

Five days of debugging. Four distinct silent failures. Zero useful error messages.

Every single problem shared the same pattern: the system accepted the bad input, returned success, and failed somewhere downstream without signaling what went wrong. The 200 OK that means failure. The build that succeeds with a placeholder SDK. The container that crashes without logs.

If I'd had Sentry in the container from day one, I would have caught the import failure, the UID crash, and the empty response pattern within hours instead of days. Observability isn't optional for agent deployments. The infrastructure actively hides failures from you.

Three principles I'm carrying forward:

**1. Never trust a 200 OK from a new service.** Validate the response body. If it's empty, something broke silently upstream.

**2. Test imports at container startup, before anything else.** A try/except around every critical import with an explicit log line. If the SDK is fake, you'll know in the first second.

**3. Read the sample repos, not just the docs.** The Dockerfile in AWS's example repo had `USER 1000`. The documentation never mentioned it. The sample code is sometimes the real documentation.

I've since added Sentry to my agent pipeline for my security posture scanner project. The trace waterfalls catch problems in seconds that would have taken me hours with print statements. Lesson learned the hard way.

---

*All errors described above are from July 2026 on AgentCore's GA release. Some may be fixed by the time you read this. The patterns of silent failure in new AWS services are probably eternal.*
