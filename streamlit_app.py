"""
AWS Security Posture Agent - Streamlit Dashboard
Multi-Agent Security Scanner with AI Observability
"""
import streamlit as st
import json
import time
import os
import sys
import re

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

st.set_page_config(
    page_title="AWS Security Posture Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        border: 1px solid #1f4068;
    }
    .main-header h1 {
        color: #e94560;
        margin: 0;
        font-size: 2.2rem;
    }
    .main-header p {
        color: #a8b2d1;
        margin: 0.5rem 0 0 0;
        font-size: 1rem;
    }
    .posture-score {
        text-align: center;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
    }
    .posture-score .score {
        font-size: 3.5rem;
        font-weight: bold;
    }
    .posture-score .label {
        font-size: 1rem;
        margin-top: 0.3rem;
    }
    .severity-card {
        text-align: center;
        border-radius: 10px;
        padding: 1.2rem;
        margin: 0.3rem;
    }
    .severity-card .count {
        font-size: 2.2rem;
        font-weight: bold;
    }
    .severity-card .label {
        font-size: 0.85rem;
        margin-top: 0.2rem;
    }
    .agent-card {
        text-align: center;
        padding: 0.8rem;
        border-radius: 8px;
        border: 1px solid #333;
        min-height: 90px;
    }
    .agent-card .icon { font-size: 1.5rem; }
    .agent-card .name { font-size: 0.7rem; color: #888; margin-top: 0.2rem; }
    .agent-card .status { font-size: 0.8rem; margin-top: 0.3rem; }
    .resource-pill {
        display: inline-block;
        background: #1a1a2e;
        border: 1px solid #1f4068;
        border-radius: 20px;
        padding: 0.3rem 0.8rem;
        margin: 0.2rem;
        font-size: 0.85rem;
    }
    div[data-testid="stMetric"] {
        background: #0e1117;
        border: 1px solid #1f4068;
        border-radius: 8px;
        padding: 1rem;
    }
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #e94560, #0f3460);
    }
</style>
""", unsafe_allow_html=True)


def parse_findings_from_output(output_text):
    """Parse security findings from agent output to get structured counts.
    
    Handles multiple formats the LLM might produce:
    - JSON: "severity": "CRITICAL"
    - Markdown: **Severity:** CRITICAL or Severity: CRITICAL
    - Table: | CRITICAL |
    - Emoji: red/orange/yellow circle followed by severity word
    """
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for sev in counts:
        patterns = [
            r'"severity":\s*"' + sev + r'"',
            r'[Ss]everity[:\s]*\**\s*' + sev,
            r'\|\s*' + sev + r'\s*\|',
            r'[-*]\s*\**' + sev + r'\**',
            r'\b' + sev + r'\b.*?(?:finding|issue|risk|vulnerability)',
            r'(?:finding|issue|risk|vulnerability).*?\b' + sev + r'\b',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, output_text, re.IGNORECASE)
            if matches:
                counts[sev] = max(counts[sev], len(matches))

    # Also check RiskScorer-style output for counts
    # Pattern: "CRITICAL: 12" or "Critical findings: 5"
    for sev in counts:
        count_pattern = r'(?:' + sev + r')\s*[:\-]?\s*(\d+)'
        match = re.search(count_pattern, output_text, re.IGNORECASE)
        if match:
            parsed_count = int(match.group(1))
            if parsed_count > counts[sev]:
                counts[sev] = parsed_count

    return counts



def parse_resources_from_output(output_text):
    """Try to extract resource counts from ResourceDiscovery output."""
    resources = {}

    service_patterns = [
        ("EC2 Instances", r'"ec2".*?"count":\s*(\d+)'),
        ("S3 Buckets", r'"s3".*?"count":\s*(\d+)'),
        ("Lambda Functions", r'"lambda".*?"count":\s*(\d+)'),
        ("Security Groups", r'"security_groups".*?"count":\s*(\d+)'),
        ("IAM Roles", r'"iam_roles".*?"count":\s*(\d+)'),
        ("IAM Users", r'"iam_users".*?"count":\s*(\d+)'),
        ("API Gateways", r'"api_gateway".*?"count":\s*(\d+)'),
        ("DynamoDB Tables", r'"dynamodb".*?"count":\s*(\d+)'),
    ]

    for name, pattern in service_patterns:
        match = re.search(pattern, output_text, re.DOTALL | re.IGNORECASE)
        if match:
            resources[name] = int(match.group(1))

    return resources


def run_scan():
    """Execute the security posture scan pipeline."""
    from dotenv import load_dotenv
    load_dotenv()

    import sentry_sdk
    from security_posture.monitoring import init_sentry, TASK_AGENT_MAP
    from security_posture.crew import SecurityPosture
    from sentry_sdk import start_span

    init_sentry()

    agent_names = list(TASK_AGENT_MAP.values())
    agent_icons = ["🗺️", "🔍", "📋", "⚡", "🔧"]
    agent_descriptions = [
        "Inventory resources",
        "Find vulnerabilities",
        "Map to CIS benchmarks",
        "Score risk levels",
        "Generate fix commands",
    ]
    agent_timings = {}
    agent_outputs = {}

    # Progress section
    st.markdown("### 🚀 Scan in progress")
    progress_bar = st.progress(0)
    status_text = st.empty()

    # Agent progress cards
    agent_container = st.container()
    cols = agent_container.columns(5)
    placeholders = []
    for i, (icon, name, desc) in enumerate(zip(agent_icons, agent_names, agent_descriptions)):
        with cols[i]:
            ph = st.empty()
            ph.markdown(
                f"<div class='agent-card'>"
                f"<div class='icon'>{icon}</div>"
                f"<div class='name'>{name}</div>"
                f"<div style='font-size:0.65rem;color:#555;'>{desc}</div>"
                f"<div class='status'>⏳ Waiting</div>"
                f"</div>", unsafe_allow_html=True)
            placeholders.append(ph)

    st.markdown("")

    with sentry_sdk.start_transaction(op="security_scan", name="Security Posture Scan") as txn:
        txn.set_data("pipeline.agents_count", 5)
        txn.set_data("pipeline.model", "amazon.nova-pro-v1:0")
        txn.set_data("source", "streamlit_ui")

        try:
            posture = SecurityPosture()
            crew_instance = posture.crew()
            tasks = crew_instance.tasks
            task_outputs = []
            total_tasks = len(tasks)

            for i, task_obj in enumerate(tasks):
                task_names_list = list(TASK_AGENT_MAP.keys())
                task_name = task_names_list[i] if i < len(task_names_list) else f"task_{i}"
                agent_name = TASK_AGENT_MAP.get(task_name, f"Agent_{i+1}")

                progress_bar.progress(int((i / total_tasks) * 100))
                status_text.markdown(f"**🤖 {agent_name}** is analyzing...")

                # Mark as running
                placeholders[i].markdown(
                    f"<div class='agent-card' style='border-color:#e94560;background:#1a1a2e;'>"
                    f"<div class='icon'>{agent_icons[i]}</div>"
                    f"<div class='name' style='color:#e94560;'>{agent_name}</div>"
                    f"<div style='font-size:0.65rem;color:#e94560;'>{agent_descriptions[i]}</div>"
                    f"<div class='status'>🔄 Running...</div>"
                    f"</div>", unsafe_allow_html=True)

                with start_span(op="gen_ai.invoke_agent", name=f"invoke_agent {agent_name}") as span:
                    span.set_data("gen_ai.operation.name", "invoke_agent")
                    span.set_data("gen_ai.agent.name", agent_name)
                    span.set_data("gen_ai.request.model", "amazon.nova-pro-v1:0")

                    task_start = time.time()
                    task_output = task_obj.execute_sync(
                        agent=task_obj.agent,
                        context="\n\n".join(str(o) for o in task_outputs) if task_outputs else "",
                        tools=task_obj.agent.tools if task_obj.agent else [],
                    )
                    elapsed = time.time() - task_start

                    task_outputs.append(task_output)
                    agent_timings[agent_name] = round(elapsed, 1)
                    agent_outputs[agent_name] = str(task_output)

                    span.set_data("duration_seconds", round(elapsed, 2))
                    span.set_data("output_length_chars", len(str(task_output)))

                # Mark as done
                placeholders[i].markdown(
                    f"<div class='agent-card' style='border-color:#2ed573;'>"
                    f"<div class='icon'>{agent_icons[i]}</div>"
                    f"<div class='name' style='color:#2ed573;'>{agent_name}</div>"
                    f"<div style='font-size:0.65rem;color:#2ed573;'>{agent_descriptions[i]}</div>"
                    f"<div class='status'>✅ {elapsed:.1f}s</div>"
                    f"</div>", unsafe_allow_html=True)

            # Write report
            if task_outputs:
                with open("security_report.md", "w") as f:
                    f.write(str(task_outputs[-1]))

            progress_bar.progress(100)
            status_text.markdown("**✅ Scan complete!**")
            txn.set_status("ok")
            sentry_sdk.flush(timeout=10)

            return {
                "timings": agent_timings,
                "outputs": agent_outputs,
                "total_time": sum(agent_timings.values()),
            }

        except Exception as e:
            txn.set_status("internal_error")
            sentry_sdk.capture_exception(e)
            sentry_sdk.flush(timeout=5)
            st.error(f"❌ Pipeline failed: {e}")
            return None


def display_results(results):
    """Display scan results."""
    st.markdown("---")

    # === POSTURE SCORE ===
    posture_score = 20
    if "RiskScorer" in results["outputs"]:
        score_match = re.search(
            r"(?:posture|overall).*?(\d{1,2})\s*/?\s*100",
            results["outputs"]["RiskScorer"], re.IGNORECASE)
        if score_match:
            posture_score = int(score_match.group(1))

    if posture_score >= 80:
        score_color, score_bg, score_label = "#2ed573", "#1a2e1f", "STRONG"
    elif posture_score >= 60:
        score_color, score_bg, score_label = "#ffa502", "#2e2a1a", "MODERATE"
    elif posture_score >= 40:
        score_color, score_bg, score_label = "#ff6b35", "#2e211a", "WEAK"
    else:
        score_color, score_bg, score_label = "#ff4757", "#2e1a1a", "CRITICAL"

    score_col, metrics_col = st.columns([1, 2])

    with score_col:
        st.markdown(
            f"<div class='posture-score' style='background:{score_bg};border:2px solid {score_color};'>"
            f"<div class='score' style='color:{score_color};'>{posture_score}/100</div>"
            f"<div class='label' style='color:{score_color};'>Security Posture: {score_label}</div>"
            f"</div>", unsafe_allow_html=True)

    with metrics_col:
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("⏱️ Total Scan Time", f"{results['total_time']:.0f}s")
        with m2:
            st.metric("🤖 Agents Executed", "5")
        with m3:
            slowest = max(results["timings"], key=results["timings"].get)
            st.metric("🐌 Bottleneck", f"{slowest}", f"{results['timings'][slowest]}s")

    # === RESOURCE INVENTORY ===
    if "ResourceDiscovery" in results["outputs"]:
        resources = parse_resources_from_output(results["outputs"]["ResourceDiscovery"])
        if resources:
            st.markdown("---")
            st.markdown("### 📦 Resources discovered")
            pills_html = " ".join(
                f"<span class='resource-pill'>{name}: <b>{count}</b></span>"
                for name, count in resources.items() if count > 0
            )
            total = sum(resources.values())
            pills_html += f" <span class='resource-pill'>Total: <b>{total}</b></span>"
            st.markdown(pills_html, unsafe_allow_html=True)

    # === FINDINGS BY SEVERITY ===
    st.markdown("---")
    st.markdown("### 🚨 Security findings")

    # Combine SecurityScanner + RiskScorer outputs for severity parsing
    all_scanner_text = results["outputs"].get("SecurityScanner", "") + "\n" + results["outputs"].get("RiskScorer", "")
    counts = parse_findings_from_output(all_scanner_text)
    total_findings = sum(counts.values())

    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        st.markdown(
            f"<div class='severity-card' style='background:#2d1f1f;border:2px solid #ff4757;'>"
            f"<div class='count' style='color:#ff4757;'>{counts['CRITICAL']}</div>"
            f"<div class='label' style='color:#ff4757;'>Critical</div></div>",
            unsafe_allow_html=True)
    with f2:
        st.markdown(
            f"<div class='severity-card' style='background:#2d2117;border:2px solid #ff6b35;'>"
            f"<div class='count' style='color:#ff6b35;'>{counts['HIGH']}</div>"
            f"<div class='label' style='color:#ff6b35;'>High</div></div>",
            unsafe_allow_html=True)
    with f3:
        st.markdown(
            f"<div class='severity-card' style='background:#2d2a17;border:2px solid #ffa502;'>"
            f"<div class='count' style='color:#ffa502;'>{counts['MEDIUM']}</div>"
            f"<div class='label' style='color:#ffa502;'>Medium</div></div>",
            unsafe_allow_html=True)
    with f4:
        st.markdown(
            f"<div class='severity-card' style='background:#1a2233;border:2px solid #70a1ff;'>"
            f"<div class='count' style='color:#70a1ff;'>{counts['LOW']}</div>"
            f"<div class='label' style='color:#70a1ff;'>Low</div></div>",
            unsafe_allow_html=True)
    with f5:
        st.markdown(
            f"<div class='severity-card' style='background:#1a1a2e;border:2px solid #a8b2d1;'>"
            f"<div class='count' style='color:#a8b2d1;'>{total_findings}</div>"
            f"<div class='label' style='color:#a8b2d1;'>Total</div></div>",
            unsafe_allow_html=True)

    # === AGENT PERFORMANCE ===
    st.markdown("---")
    st.markdown("### ⏱️ Agent execution times")
    st.bar_chart(results["timings"], color="#e94560", height=250)

    # === DETAILED OUTPUTS ===
    st.markdown("---")
    st.markdown("### 📋 Detailed outputs")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔍 Security Findings",
        "📜 Compliance",
        "⚡ Risk Scores",
        "🔧 Remediation",
        "🗺️ Inventory",
    ])

    with tab1:
        if "SecurityScanner" in results["outputs"]:
            st.markdown(results["outputs"]["SecurityScanner"][:8000])

    with tab2:
        if "ComplianceChecker" in results["outputs"]:
            st.markdown(results["outputs"]["ComplianceChecker"][:8000])

    with tab3:
        if "RiskScorer" in results["outputs"]:
            st.markdown(results["outputs"]["RiskScorer"][:8000])

    with tab4:
        if "RemediationPlanner" in results["outputs"]:
            st.markdown(results["outputs"]["RemediationPlanner"][:8000])

    with tab5:
        if "ResourceDiscovery" in results["outputs"]:
            st.markdown(results["outputs"]["ResourceDiscovery"][:8000])

    # === DOWNLOAD ===
    st.markdown("---")
    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        if os.path.exists("security_report.md"):
            with open("security_report.md", "r") as f:
                report_content = f.read()
            st.download_button(
                label="📥 Download Report",
                data=report_content,
                file_name="security_posture_report.md",
                mime="text/markdown",
                use_container_width=True,
            )
    with dl2:
        all_data = json.dumps(results, indent=2, default=str)
        st.download_button(
            label="📊 Export JSON",
            data=all_data,
            file_name="security_scan_data.json",
            mime="application/json",
            use_container_width=True,
        )
    with dl3:
        st.link_button(
            "📡 Sentry Traces",
            "https://sentry.io",
            use_container_width=True,
        )


# ============================================================
# MAIN UI
# ============================================================

# Header
st.markdown("""
<div class="main-header">
    <h1>🛡️ AWS Security Posture Agent</h1>
    <p>5 AI agents scan your AWS account for misconfigurations, map to CIS benchmarks, score risk, and generate fix commands.</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    st.markdown("""
    | | |
    |--|--|
    | **Region** | us-east-1 |
    | **LLM** | Bedrock Nova Pro |
    | **Agents** | 5 (Sequential) |
    | **Tools** | 5 Custom (boto3) |
    | **Monitor** | Sentry AI |
    """)

    st.markdown("---")
    st.markdown("### 🏗️ Agent pipeline")
    st.code("""
ResourceDiscovery
  └─ aws_resource_scanner
SecurityScanner
  ├─ security_group_analyzer
  ├─ s3_config_checker
  ├─ iam_analyzer
  ├─ ec2_security_checker
  └─ lambda_security_checker
ComplianceChecker
  └─ CIS Benchmark mapping
RiskScorer
  └─ Severity x Blast x Exploit
RemediationPlanner
  └─ AWS CLI fix commands
    """, language=None)

    st.markdown("---")

    sentry_dsn = os.getenv("SENTRY_DSN", "")
    if sentry_dsn:
        st.markdown("### 📡 Sentry AI Monitoring")
        st.success("Connected ✅")
        st.caption("Every scan sends traces with:")
        st.caption("• gen_ai.invoke_agent x 5")
        st.caption("• gen_ai.execute_tool x 5")
        st.caption("• Token usage per agent")
    else:
        st.warning("⚠️ SENTRY_DSN not set")

    st.markdown("---")
    st.markdown("[GitHub](https://github.com/simplynadaf/aws-security-posture-agent) · "
               "[DEV.to](https://dev.to/sarvarnadaf) · "
               "[Sentry](https://sentry.io)")

# What it checks
with st.expander("ℹ️ What does this agent check?", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""
        **🖥️ Compute**
        - EC2 instance profiles
        - Unencrypted EBS volumes
        - Public IP exposure
        - Default SG attached
        - Stopped/orphaned instances
        """)
    with c2:
        st.markdown("""
        **🌐 Network**
        - Open SSH/RDP/DB ports
        - Wide port ranges (0-65535)
        - Default SG with rules
        - Stale launch-wizard SGs
        """)
    with c3:
        st.markdown("""
        **🪣 Storage**
        - Missing S3 encryption
        - Versioning disabled
        - Public access blocks
        - Bucket policies
        """)
    with c4:
        st.markdown("""
        **🔑 Identity & Lambda**
        - AdministratorAccess roles
        - Users without MFA
        - Access key rotation (>90d)
        - Lambda overprivileged roles
        - Missing Dead Letter Queues
        """)

# Scan button
st.markdown("")
col_btn, col_info = st.columns([1, 3])
with col_btn:
    scan_button = st.button("🔍 Start Security Scan", type="primary", use_container_width=True)
with col_info:
    st.caption("Scans 7 AWS services across your account. Takes ~60 seconds. "
              "Results include findings, CIS mapping, risk scores, and copy-paste CLI fixes.")

# Run
if scan_button:
    st.markdown("---")
    results = run_scan()
    if results:
        display_results(results)

elif os.path.exists("security_report.md"):
    st.markdown("---")
    st.info("📄 Previous scan report available. Click **Start Security Scan** for fresh results.")
    with st.expander("📋 Last scan report", expanded=False):
        with open("security_report.md", "r") as f:
            st.markdown(f.read()[:10000])

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#555;font-size:0.8rem;'>"
    "AWS Security Posture Agent · Built for DEV Summer Bug Smash 2026 · "
    "<a href='https://github.com/simplynadaf/aws-security-posture-agent' style='color:#e94560;'>Sarvar Nadaf</a>"
    "</div>",
    unsafe_allow_html=True,
)
