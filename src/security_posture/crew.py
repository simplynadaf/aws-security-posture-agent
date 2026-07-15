import os
import time
import sentry_sdk
from sentry_sdk import start_span

from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent

from security_posture.tools import (
    AWSResourceScanner,
    SecurityGroupAnalyzer,
    S3ConfigChecker,
    IAMAnalyzer,
    EC2SecurityChecker,
    LambdaSecurityChecker,
)
from security_posture.monitoring import TASK_AGENT_MAP

# Configure Bedrock LLM
bedrock_llm = LLM(
    model="bedrock/amazon.nova-pro-v1:0",
    region_name="us-east-1",
)


def _make_task_callback(agent_name: str):
    """Create a task callback that records agent completion metrics in Sentry."""
    def callback(output):
        sentry_sdk.add_breadcrumb(
            category="agent",
            message=f"Agent '{agent_name}' completed task",
            level="info",
            data={
                "agent_name": agent_name,
                "output_length": len(str(output)) if output else 0,
            },
        )
    return callback


@CrewBase
class SecurityPosture():
    """SecurityPosture crew - Multi-agent AWS security scanner with Sentry AI monitoring."""

    agents: list[BaseAgent]
    tasks: list[Task]

    @agent
    def resource_discovery(self) -> Agent:
        return Agent(
            config=self.agents_config["resource_discovery"],
            tools=[AWSResourceScanner()],
            llm=bedrock_llm,
            verbose=True,
        )

    @agent
    def security_scanner(self) -> Agent:
        return Agent(
            config=self.agents_config["security_scanner"],
            tools=[
                SecurityGroupAnalyzer(),
                S3ConfigChecker(),
                IAMAnalyzer(),
                EC2SecurityChecker(),
                LambdaSecurityChecker(),
            ],
            llm=bedrock_llm,
            verbose=True,
        )

    @agent
    def compliance_checker(self) -> Agent:
        return Agent(
            config=self.agents_config["compliance_checker"],
            llm=bedrock_llm,
            verbose=True,
        )

    @agent
    def risk_scorer(self) -> Agent:
        return Agent(
            config=self.agents_config["risk_scorer"],
            llm=bedrock_llm,
            verbose=True,
        )

    @agent
    def remediation_planner(self) -> Agent:
        return Agent(
            config=self.agents_config["remediation_planner"],
            llm=bedrock_llm,
            verbose=True,
        )

    @task
    def resource_discovery_task(self) -> Task:
        return Task(
            config=self.tasks_config["resource_discovery_task"],
            callback=_make_task_callback("ResourceDiscovery"),
        )

    @task
    def security_scanning_task(self) -> Task:
        return Task(
            config=self.tasks_config["security_scanning_task"],
            callback=_make_task_callback("SecurityScanner"),
        )

    @task
    def compliance_check_task(self) -> Task:
        return Task(
            config=self.tasks_config["compliance_check_task"],
            callback=_make_task_callback("ComplianceChecker"),
        )

    @task
    def risk_scoring_task(self) -> Task:
        return Task(
            config=self.tasks_config["risk_scoring_task"],
            callback=_make_task_callback("RiskScorer"),
        )

    @task
    def remediation_planning_task(self) -> Task:
        return Task(
            config=self.tasks_config["remediation_planning_task"],
            output_file="security_report.md",
            callback=_make_task_callback("RemediationPlanner"),
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
