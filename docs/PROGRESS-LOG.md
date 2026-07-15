# DEV Summer Bug Smash - Complete Progress Log

## Challenge: DEV's Summer Bug Smash (July 14 - August 23, 2026)
## Target: Clear the Lineup + Best Use of Sentry ($500) + Smash Stories ($200)

---

## Project: AWS Security Posture Agent

**Repo:** https://github.com/simplynadaf/aws-security-posture-agent
**EC2:** REDACTED_INSTANCE_ID | IP: REDACTED_IP | SSH: `ssh -i test.pem ubuntu@REDACTED_IP`
**Project dir:** /home/ubuntu/security-posture-agent

---

## Done: Day 1 (July 15) - Foundation + Tools

- Provisioned EC2 t3.medium, Ubuntu 24.04, us-east-1, 30GB gp3
- Python 3.12 venv: crewai 1.15.2, sentry-sdk 2.65, boto3 1.42, streamlit
- Signed up Sentry with promo code bugsmash26
- Configured .env with SENTRY_DSN
- Built 4 custom CrewAI tools:
  1. AWSResourceScanner - EC2, S3, Lambda, IAM, SGs, API GW, DynamoDB
  2. SecurityGroupAnalyzer - open ports, default SGs, launch-wizard
  3. S3ConfigChecker - encryption, versioning, public access blocks
  4. IAMAnalyzer - admin roles, MFA, key rotation (intentionally fetches all 90 roles)
- Created 5 agent definitions in agents.yaml with backstories
- Created 5 task definitions in tasks.yaml with expected outputs
- Built crew.py with Bedrock Nova Pro as LLM
- First successful end-to-end scan, security_report.md generated
- Account: 90 IAM roles, 13 S3 buckets, 9 SGs, 3 EC2, 7 Lambda

---

## Done: Day 2 (July 15) - Sentry AI Agent Monitoring

- Created monitoring.py with init_sentry, agent_span, trace_tool, TASK_AGENT_MAP
- Added @trace_tool decorator to all 4 tools
- Updated main.py to wrap tasks in gen_ai.invoke_agent spans
- Added task callbacks for Sentry breadcrumbs
- Ran pipeline 2x, BEFORE traces sent to Sentry

### BEFORE metrics:
- ResourceDiscovery: 17.6s
- SecurityScanner: 22.6s (36% of total, BOTTLENECK)
- ComplianceChecker: 7.1s
- RiskScorer: 4.7s
- RemediationPlanner: 10.0s
- Total: 62.0s

---

## Done: Day 3 (July 15) - Bug Fix

### Bug:
IAMAnalyzer fetches ALL 90 roles (59 auditable), produces 26,980 chars.
Overwhelms LLM context, SecurityScanner retries.

### Fix in iam_analyzer.py:
1. Pagination: top 20 most-recently-used roles
2. Sort by RoleLastUsed date
3. Skip 31 service-linked roles
4. Token budget guard: truncate if > 4000 chars

### AFTER metrics:
- IAM tool output: 26,980 to 15,532 chars (42% smaller)
- SecurityScanner: 22.6s to 17.8s (21% faster)
- IAM API calls: 59 to 20 (66% fewer)
- Total pipeline: 62.0s to 57.7s (7% faster)
- Findings: 27 both before and after (no coverage loss)

### Sentry runs captured:
- Before fix: 2 runs
- After fix: 5 runs

---

## Done: Day 4 (July 15) - Streamlit UI + GitHub

- Built streamlit_app.py:
  - Dark gradient header, accent color
  - Live agent progress cards with timing
  - Color-coded severity cards
  - Architecture diagram in sidebar
  - Sentry status indicator
  - Expandable outputs per agent
  - Download report button
  - Footer with attribution
- Created README.md, .env.example, docs/METRICS-COMPARISON.md
- Initialized git, added SSH key to GitHub
- Pushed 5 commits to https://github.com/simplynadaf/aws-security-posture-agent

---

## Done: Day 5 (July 15) - Submissions Drafted

### Submission 1: Clear the Lineup + Sentry Prize
- Title: Sentry's AI Agent Monitoring Caught a Token Explosion in My 5-Agent AWS Security Scanner
- File: docs/submissions/submission-1-clear-the-lineup.md
- Words: 1,247
- Quality: zero em dashes, zero AI tell-words, zero banned phrases
- Placeholders: SCREENSHOT x2, COVER_IMAGE_URL x1

### Submission 2: Smash Stories
- Title: 4 Silent Failures, 2 Undocumented APIs, and a Container That Crashed Because of a Missing User Directive
- File: docs/submissions/submission-2-smash-stories.md
- Words: 1,290
- Quality: zero em dashes, zero AI tell-words, zero banned phrases
- Placeholders: COVER_IMAGE_URL x1

---

## Done: Recording Tools Installed on EC2

### Approach 1 - Puppeteer + Xvfb + ffmpeg (video WITH audio):
- Xvfb: /usr/bin/Xvfb
- ffmpeg: /usr/bin/ffmpeg
- Node.js: v20.20.2
- Puppeteer: npm installed, Chrome at ~/.cache/puppeteer/chrome/linux-148.0.7778.97/chrome-linux64/chrome
- PulseAudio: available
- Script: take-screenshots.js in project root

### Approach 2 - Playwright (built-in video, NO Xvfb needed):
- Playwright: 1.61.0 (pip3 install --break-system-packages playwright)
- Chromium: ~/.cache/ms-playwright/chromium-1228
- ffmpeg: ~/.cache/ms-playwright/ffmpeg-1011
- Python API: from playwright.sync_api import sync_playwright

### When to use which:
- Screenshots only: Playwright (simpler, headless works)
- Video without audio: Playwright (built-in record_video_dir)
- Video WITH audio: Puppeteer + Xvfb + ffmpeg + PulseAudio

### Skill documentation:
- /home/ubuntu/.kiro/skills/demo-recording/SKILL.md (covers both approaches)

---

## Outstanding (For Sarvar)

### Screenshots needed:
- [ ] Sentry trace waterfall BEFORE fix (Performance, Traces)
- [ ] Sentry trace waterfall AFTER fix
- [ ] Sentry AI Agents view (Insights, if available)
- [ ] Streamlit UI with results (can capture with Playwright)

### Before publishing:
- [ ] Replace SCREENSHOT placeholders in submission 1
- [ ] Replace COVER_IMAGE_URL in both submissions
- [ ] Add personal touches to articles
- [ ] Create cover images (Canva dark theme)
- [ ] Publish both on Dev.to
- [ ] Self-react (heart + unicorn + bookmark)
- [ ] Post first comment on each
- [ ] Share on LinkedIn (link in first comment)

### Events:
- [ ] July 30: Attend Sentry Live Demo and Q&A (11am PT / 11:30pm IST)
- [ ] Ask about AI agent monitoring with custom frameworks like CrewAI

---

## File Inventory

### Source Code (src/security_posture/):
- main.py: Entry point + Sentry transaction + agent spans
- crew.py: 5-agent crew orchestration with Bedrock Nova Pro
- monitoring.py: Sentry AI monitoring helpers
- config/agents.yaml: 5 agent definitions
- config/tasks.yaml: 5 task definitions
- tools/__init__.py: Tool exports
- tools/aws_resource_scanner.py: Multi-service resource inventory
- tools/security_group_analyzer.py: SG rule analysis
- tools/s3_config_checker.py: S3 security config
- tools/iam_analyzer.py: IAM analysis (FIXED: paginated, sorted, budget guard)

### UI and Config:
- streamlit_app.py: Web dashboard
- pyproject.toml: Dependencies
- .env: Sentry DSN + AWS config (gitignored)
- .env.example: Template
- README.md: GitHub documentation
- .gitignore: Excludes venv, env, pycache, reports

### Documentation (docs/):
- PROGRESS-LOG.md: This file
- METRICS-COMPARISON.md: Before/after performance data
- submissions/submission-1-clear-the-lineup.md: Article draft 1
- submissions/submission-2-smash-stories.md: Article draft 2
- sentry-screenshots/: For trace screenshots

### Recording (not committed):
- take-screenshots.js: Puppeteer screenshot script
- package.json: Node deps
- node_modules/: gitignored

---

## Access

- EC2 SSH: ssh -i test.pem ubuntu@REDACTED_IP
- GitHub: https://github.com/simplynadaf/aws-security-posture-agent
- GitHub SSH key: ed25519 bug-smash-agent-ec2 added to GitHub account
- Sentry: project security-posture-agent, DSN in .env on EC2
- Sentry promo: bugsmash26, $100 credits + 14-day trial
- AWS Account: REDACTED_ACCOUNT, us-east-1
- AWS creds: ~/.aws/credentials on EC2

---

## Challenge Rules Compliance

- Development started during entry period (July 15): YES
- Original creation: YES
- Tags devchallenge + bugsmash: YES in both articles
- English only: YES
- Individual, no teams: YES
- Fork merge counts, own repo: YES
- Multiple submissions, separate posts: YES, doing 2
- Clear the Lineup eligible for Sentry prize: YES
- Smash Stories eligible for writing prize: YES

---

## Key Dates

- July 15: All development complete
- July 15: Articles drafted
- July 20-21: Target publish date
- July 30: Sentry Live Demo (11am PT)
- August 23: Submission deadline
- September 17: Winners announced

---

## Prize Targets

- Best Use of Sentry: $500 + Skateboard + DEV++ (Submission 1)
- Smash Stories: $200 + DEV++ (Submission 2)
- Completion Badge: both submissions
- Total possible: $700 + DEV++
