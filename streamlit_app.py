"""
AWS Security Posture Agent - Streamlit Dashboard
Multi-Agent Security Scanner with AI Observability
"""
import streamlit as st
import json
import time
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

st.set_page_config(
    page_title="AWS Security Posture Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for better styling
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
    .metric-card {
        background: #1a1a2e;
        border: 1px solid #1f4068;
        border-radius: 10px;
        padding: 1.2rem;
        text-align: center;
    }
    .severity-critical { color: #ff4757; font-weight: bold; }
    .severity-high { color: #ff6b35; font-weight: bold; }
    .severity-medium { color: #ffa502; font-weight: bold; }
    .severity-low { color: #70a1ff; font-weight: bold; }
    .agent-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
        margin: 0.2rem;
    }
    .scan-btn button {
        background: linear-gradient(135deg, #e94560, #c23152) !important;
        border: none !important;
        font-size: 1.1rem !important;
        padding: 0.8rem 2rem !important;
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
    agent_timings = {}
    agent_outputs = {}

    # Progress display
    progress_bar = st.progress(0)
    status_text = st.empty()
    agent_status = st.container()

    cols = agent_status.columns(5)
    status_placeholders = []
    for i, (icon, name) in enumerate(zip(agent_icons, agent_names)):
        with cols[i]:
            ph = st.empty()
            ph.markdown(f"<div style='text-align:center;padding:0.5rem;border:1px solid #333;border-radius:8px;'>"
                       f"<div style='font-size:1.5rem;'>{icon}</div>"
                       f"<div style='font-size:0.7rem;color:#666;'>{name}</div>"
                       f"<div style='font-size:0.8rem;'>⏳</div></div>", unsafe_allow_html=True)
            status_placeholders.append(ph)

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

                progress_pct = int((i / total_tasks) * 100)
                progress_bar.progress(progress_pct)
                status_text.markdown(f"**🤖 Running {agent_name}...**")

                # Update agent card to "running"
                status_placeholders[i].markdown(
                    f"<div style='text-align:center;padding:0.5rem;border:1px solid #e94560;border-radius:8px;background:#1a1a2e;'>"
                    f"<div style='font-size:1.5rem;'>{agent_icons[i]}</div>"
                    f"<div style='font-size:0.7rem;color:#e94560;'>{agent_name}</div>"
                    f"<div style='font-size:0.8rem;'>🔄 Running...</div></div>", unsafe_allow_html=True)

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

                # Update agent card to "done"
                status_placeholders[i].markdown(
                    f"<div style='text-align:center;padding:0.5rem;border:1px solid #2ed573;border-radius:8px;'>"
                    f"<div style='font-size:1.5rem;'>{agent_icons[i]}</div>"
                    f"<div style='font-size:0.7rem;color:#2ed573;'>{agent_name}</div>"
                    f"<div style='font-size:0.8rem;'>✅ {elapsed:.1f}s</div></div>", unsafe_allow_html=True)

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


def display_results(results: dict):
    """Display scan results in the dashboard."""
    st.markdown("---")

    # Top-level metrics
    st.subheader("📊 Scan Summary")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("⏱️ Total Time", f"{results['total_time']:.0f}s")
    with m2:
        st.metric("🤖 Agents Run", "5")
    with m3:
        slowest = max(results["timings"], key=results["timings"].get)
        st.metric("🐌 Slowest", f"{slowest} ({results['timings'][slowest]}s)")
    with m4:
        fastest = min(results["timings"], key=results["timings"].get)
        st.metric("⚡ Fastest", f"{fastest} ({results['timings'][fastest]}s)")

    # Agent performance chart
    st.markdown("---")
    st.subheader("⏱️ Agent Execution Times")

    chart_data = {name: [timing] for name, timing in results["timings"].items()}
    st.bar_chart(results["timings"], color="#e94560")

    # Findings summary
    st.markdown("---")
    st.subheader("🚨 Security Findings")

    if "SecurityScanner" in results["outputs"]:
        scanner_out = results["outputs"]["SecurityScanner"]

        # Count findings by severity
        critical = scanner_out.upper().count("CRITICAL")
        high = scanner_out.upper().count("\"HIGH\"") + scanner_out.upper().count("'HIGH'")
        medium = scanner_out.upper().count("\"MEDIUM\"") + scanner_out.upper().count("'MEDIUM'")
        low = scanner_out.upper().count("\"LOW\"") + scanner_out.upper().count("'LOW'")

        f1, f2, f3, f4 = st.columns(4)
        with f1:
            st.markdown(f"""
            <div style='text-align:center;background:#2d1f1f;border:2px solid #ff4757;border-radius:10px;padding:1rem;'>
                <div style='font-size:2rem;color:#ff4757;font-weight:bold;'>{critical}</div>
                <div style='color:#ff4757;font-size:0.9rem;'>Critical</div>
            </div>""", unsafe_allow_html=True)
        with f2:
            st.markdown(f"""
            <div style='text-align:center;background:#2d2117;border:2px solid #ff6b35;border-radius:10px;padding:1rem;'>
                <div style='font-size:2rem;color:#ff6b35;font-weight:bold;'>{high}</div>
                <div style='color:#ff6b35;font-size:0.9rem;'>High</div>
            </div>""", unsafe_allow_html=True)
        with f3:
            st.markdown(f"""
            <div style='text-align:center;background:#2d2a17;border:2px solid #ffa502;border-radius:10px;padding:1rem;'>
                <div style='font-size:2rem;color:#ffa502;font-weight:bold;'>{medium}</div>
                <div style='color:#ffa502;font-size:0.9rem;'>Medium</div>
            </div>""", unsafe_allow_html=True)
        with f4:
            st.markdown(f"""
            <div style='text-align:center;background:#1a2233;border:2px solid #70a1ff;border-radius:10px;padding:1rem;'>
                <div style='font-size:2rem;color:#70a1ff;font-weight:bold;'>{low}</div>
                <div style='color:#70a1ff;font-size:0.9rem;'>Low</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("")
        with st.expander("📋 Full Security Scanner Output"):
            st.markdown(scanner_out[:6000])

    # Compliance
    if "ComplianceChecker" in results["outputs"]:
        st.markdown("---")
        st.subheader("📜 Compliance Mapping")
        with st.expander("CIS AWS Foundations Benchmark Mapping", expanded=False):
            st.markdown(results["outputs"]["ComplianceChecker"][:6000])

    # Risk Assessment
    if "RiskScorer" in results["outputs"]:
        st.markdown("---")
        st.subheader("⚡ Risk Assessment")
        with st.expander("Risk Scoring Details", expanded=False):
            st.markdown(results["outputs"]["RiskScorer"][:6000])

    # Remediation Plan
    if "RemediationPlanner" in results["outputs"]:
        st.markdown("---")
        st.subheader("🔧 Remediation Plan")
        st.markdown(results["outputs"]["RemediationPlanner"][:8000])

    # Download
    st.markdown("---")
    dl1, dl2 = st.columns(2)
    with dl1:
        if os.path.exists("security_report.md"):
            with open("security_report.md", "r") as f:
                report_content = f.read()
            st.download_button(
                label="📥 Download Full Report (Markdown)",
                data=report_content,
                file_name="security_posture_report.md",
                mime="text/markdown",
                use_container_width=True,
            )
    with dl2:
        st.link_button(
            "📊 View Sentry Traces",
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
    <p>Multi-Agent Security Scanner powered by CrewAI + Amazon Bedrock Nova Pro + Sentry AI Monitoring</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.image("https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge", width=150)
    st.markdown("---")

    st.markdown("### ⚙️ Configuration")
    st.markdown(f"""
    | Setting | Value |
    |---------|-------|
    | Region | `us-east-1` |
    | Model | `Nova Pro v1` |
    | Agents | `5 (Sequential)` |
    | Tools | `4 Custom` |
    """)

    st.markdown("---")
    st.markdown("### 🏗️ Pipeline Architecture")
    st.code("""
┌──────────────────────┐
│ 1. ResourceDiscovery  │
│    └─ aws_scanner     │
├──────────────────────┤
│ 2. SecurityScanner    │
│    ├─ sg_analyzer     │
│    ├─ s3_checker      │
│    ├─ iam_analyzer    │
│    ├─ ec2_checker     │
│    └─ lambda_checker  │
├──────────────────────┤
│ 3. ComplianceChecker  │
│    └─ CIS Benchmarks  │
├──────────────────────┤
│ 4. RiskScorer         │
│    └─ CVSS-style      │
├──────────────────────┤
│ 5. RemediationPlanner │
│    └─ AWS CLI fixes   │
└──────────────────────┘
    """, language=None)

    st.markdown("---")
    st.markdown("### 📡 Observability")
    sentry_dsn = os.getenv("SENTRY_DSN", "")
    if sentry_dsn:
        st.success("Sentry AI Monitoring ✅")
        st.caption("Traces: gen_ai.invoke_agent × 5")
        st.caption("Tools: gen_ai.execute_tool × 4")
    else:
        st.warning("⚠️ SENTRY_DSN not configured")

    st.markdown("---")
    st.markdown("### 🔗 Links")
    st.markdown("[GitHub Repo](https://github.com/simplynadaf/aws-security-posture-agent)")
    st.markdown("[Sentry Dashboard](https://sentry.io)")

# Main content area
st.markdown("")

# What it scans section
with st.expander("ℹ️ What does this agent check?", expanded=False):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""
        **🖥️ Compute**
        - EC2 instance profiles
        - Unencrypted EBS
        - Public IPs exposed
        - Default SG attached
        - Stopped instances
        """)
    with c2:
        st.markdown("""
        **🌐 Network**
        - Open ports (SSH, RDP, DB)
        - Wide port ranges
        - Default SG rules
        - Stale launch-wizard SGs
        """)
    with c3:
        st.markdown("""
        **🪣 Storage**
        - S3 encryption
        - Bucket versioning
        - Public access blocks
        - Bucket policies
        """)
    with c4:
        st.markdown("""
        **🔑 Identity + Serverless**
        - AdminAccess roles
        - Users without MFA
        - Key rotation
        - Lambda runtimes
        - Lambda role perms
        - Missing DLQs
        """)
        """)

st.markdown("")

# Scan button
col_btn, col_info = st.columns([1, 2])
with col_btn:
    scan_button = st.button("🔍 Start Security Scan", type="primary", use_container_width=True)
with col_info:
    st.caption("Scans EC2, S3, Lambda, IAM, Security Groups, API Gateway, and DynamoDB. Takes ~60 seconds.")

# Run scan
if scan_button:
    st.markdown("---")
    results = run_scan()
    if results:
        display_results(results)

# Show previous report
elif os.path.exists("security_report.md"):
    st.markdown("---")
    st.info("📄 A previous scan report is available below. Click **Start Security Scan** to run fresh.")
    with st.expander("📋 Last Scan Report", expanded=False):
        with open("security_report.md", "r") as f:
            st.markdown(f.read())

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#666;font-size:0.8rem;'>"
    "Built for DEV's Summer Bug Smash 2026 | Sarvar Nadaf | "
    "<a href='https://github.com/simplynadaf/aws-security-posture-agent'>GitHub</a>"
    "</div>",
    unsafe_allow_html=True,
)
