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
)


def run_scan():
    """Execute the security posture scan pipeline."""
    from dotenv import load_dotenv
    load_dotenv()

    import sentry_sdk
    from security_posture.monitoring import init_sentry, TASK_AGENT_MAP
    from security_posture.crew import SecurityPosture
    from sentry_sdk import start_span

    # Initialize Sentry
    init_sentry()

    progress_bar = st.progress(0, text="Initializing pipeline...")
    status_container = st.container()

    agent_timings = {}
    agent_outputs = {}

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
                task_names = list(TASK_AGENT_MAP.keys())
                task_name = task_names[i] if i < len(task_names) else f"task_{i}"
                agent_name = TASK_AGENT_MAP.get(task_name, f"Agent_{i+1}")

                progress_pct = int((i / total_tasks) * 100)
                progress_bar.progress(progress_pct, text=f"🤖 Running {agent_name}...")

                with start_span(op="gen_ai.invoke_agent", name=f"invoke_agent {agent_name}") as span:
                    span.set_data("gen_ai.operation.name", "invoke_agent")
                    span.set_data("gen_ai.agent.name", agent_name)
                    span.set_data("gen_ai.request.model", "amazon.nova-pro-v1:0")
                    span.set_data("gen_ai.pipeline.name", "security-posture-scan")

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

            # Write report
            if task_outputs:
                with open("security_report.md", "w") as f:
                    f.write(str(task_outputs[-1]))

            progress_bar.progress(100, text="✅ Scan complete!")
            txn.set_status("ok")

            # Flush Sentry
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


def parse_findings_from_output(scanner_output: str) -> list:
    """Try to extract structured findings from SecurityScanner output."""
    findings = []
    lines = scanner_output.split("\n")
    current_finding = {}

    for line in lines:
        line = line.strip()
        if "CRITICAL" in line.upper():
            if current_finding:
                findings.append(current_finding)
            current_finding = {"severity": "CRITICAL", "text": line}
        elif "HIGH" in line.upper() and ("severity" in line.lower() or "issue" in line.lower()):
            if current_finding:
                findings.append(current_finding)
            current_finding = {"severity": "HIGH", "text": line}
        elif "MEDIUM" in line.upper() and ("severity" in line.lower() or "issue" in line.lower()):
            if current_finding:
                findings.append(current_finding)
            current_finding = {"severity": "MEDIUM", "text": line}
        elif "LOW" in line.upper() and ("severity" in line.lower() or "issue" in line.lower()):
            if current_finding:
                findings.append(current_finding)
            current_finding = {"severity": "LOW", "text": line}

    if current_finding:
        findings.append(current_finding)

    return findings


def display_results(results: dict):
    """Display scan results in the dashboard."""
    st.divider()

    # Timing metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Scan Time", f"{results['total_time']:.1f}s")
    with col2:
        st.metric("Agents Executed", "5")
    with col3:
        st.metric("Slowest Agent", max(results["timings"], key=results["timings"].get))

    # Agent performance chart
    st.subheader("⏱️ Agent Performance")
    st.bar_chart(results["timings"])

    # Findings from SecurityScanner
    st.subheader("🔍 Security Findings")
    if "SecurityScanner" in results["outputs"]:
        scanner_out = results["outputs"]["SecurityScanner"]

        # Count severity mentions
        critical = scanner_out.upper().count("CRITICAL")
        high = scanner_out.upper().count("HIGH")
        medium = scanner_out.upper().count("MEDIUM")
        low = scanner_out.upper().count("LOW")

        fcol1, fcol2, fcol3, fcol4 = st.columns(4)
        with fcol1:
            st.metric("🔴 Critical", critical)
        with fcol2:
            st.metric("🟠 High", high)
        with fcol3:
            st.metric("🟡 Medium", medium)
        with fcol4:
            st.metric("🔵 Low", low)

        with st.expander("📋 Full Security Scanner Output", expanded=False):
            st.markdown(scanner_out[:5000])

    # Risk Score from RiskScorer
    if "RiskScorer" in results["outputs"]:
        st.subheader("📊 Risk Assessment")
        with st.expander("Risk Scoring Details", expanded=False):
            st.markdown(results["outputs"]["RiskScorer"][:5000])

    # Remediation Plan
    if "RemediationPlanner" in results["outputs"]:
        st.subheader("🔧 Remediation Plan")
        st.markdown(results["outputs"]["RemediationPlanner"][:8000])

    # Download report
    st.divider()
    if os.path.exists("security_report.md"):
        with open("security_report.md", "r") as f:
            report_content = f.read()
        st.download_button(
            label="📥 Download Full Report",
            data=report_content,
            file_name="security_posture_report.md",
            mime="text/markdown",
        )


# ============================================================
# MAIN UI
# ============================================================

st.title("🛡️ AWS Security Posture Agent")
st.caption("Multi-Agent Security Scanner powered by CrewAI + Amazon Bedrock + Sentry AI Monitoring")

st.divider()

# Sidebar
with st.sidebar:
    st.header("⚙️ Configuration")
    st.text_input("Region", value="us-east-1", disabled=True)
    st.text_input("Model", value="amazon.nova-pro-v1:0", disabled=True)
    st.text_input("Agents", value="5 (Sequential)", disabled=True)

    st.divider()
    st.header("🏗️ Architecture")
    st.markdown("""
    ```
    1. ResourceDiscovery
       └─ aws_resource_scanner
    2. SecurityScanner
       ├─ security_group_analyzer
       ├─ s3_config_checker
       └─ iam_analyzer
    3. ComplianceChecker
    4. RiskScorer
    5. RemediationPlanner
    ```
    """)

    st.divider()
    st.markdown("**Sentry AI Monitoring**")
    sentry_dsn = os.getenv("SENTRY_DSN", "")
    if sentry_dsn:
        st.success("✅ Connected")
    else:
        st.warning("⚠️ No SENTRY_DSN set")

# Main content
col_left, col_right = st.columns([3, 1])

with col_left:
    st.markdown("""
    This agent scans your AWS account for security misconfigurations across:
    - **EC2** instances, **S3** buckets, **Lambda** functions
    - **IAM** roles & users, **Security Groups**, **API Gateway**
    - Maps findings to **CIS AWS Foundations Benchmark**
    - Scores risk by severity, blast radius, and exploitability
    - Generates **copy-paste AWS CLI fix commands**
    """)

with col_right:
    scan_button = st.button("🔍 Start Security Scan", type="primary", use_container_width=True)

if scan_button:
    with st.spinner("Running 5-agent security scan pipeline..."):
        results = run_scan()
    if results:
        display_results(results)

# Show previous report if exists
elif os.path.exists("security_report.md"):
    st.info("📄 Previous scan report available. Click 'Start Security Scan' to run a fresh scan.")
    with st.expander("View Last Report"):
        with open("security_report.md", "r") as f:
            st.markdown(f.read())
