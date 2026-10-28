"""The swarm: an investigation crew per incident (Researcher -> Diagnostician) and a Field Tech crew that acts through One."""
from __future__ import annotations

import json
import os
from typing import Callable

from crewai import Agent, Crew, LLM, Process, Task
from crewai.mcp import MCPServerStdio
from pydantic import BaseModel

from . import parasail
from .config import PARASAIL_BASE_URL, settings
from .schemas import Action, Diagnosis, EvidenceList, TriagedIncident, IncidentCandidate
from .tools import make_tools, make_action_tools

Observer = Callable[[str, dict], None]


def parasail_llm(temperature: float = 0.2, max_tokens: int = 3000) -> LLM:
    return LLM(
        model=f"openai/{settings.parasail_model}",
        base_url=PARASAIL_BASE_URL,
        api_key=settings.parasail_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------- investigation crew


def investigation_crew(cand: IncidentCandidate, tri: TriagedIncident, robot: dict, observer: Observer | None = None, others: list[str] | None = None) -> Crew:
    tools = make_tools(cand.id, observer)
    llm = parasail_llm()

    researcher = Agent(
        role="Robotics Field Researcher",
        goal="Find the authoritative explanation of a robot fault: vendor error-code docs, driver GitHub issues, ROS Answers / Robotics StackExchange threads, service manuals.",
        backstory=(
            "You are the person the lab calls when a robot misbehaves at 2 a.m. You never guess: you search, you read the page, "
            "and you quote it. You know Universal Robots error codes (Cxxx), Dynamixel hardware error bits, ros2_control, Nav2 and lidar drivers."
        ),
        tools=tools,
        llm=llm,
        max_iter=6,
        verbose=False,
        allow_delegation=False,
    )
    diagnostician = Agent(
        role="Robot Diagnostician",
        goal="Turn log evidence plus researched sources into a ranked, cited diagnosis with concrete fix steps.",
        backstory=(
            "Senior robotics integrator. You reason from symptoms, timing and electrical context to root causes, and you only cite URLs "
            "that the researcher actually read. You say 'benign' when something is a known harmless warning."
        ),
        llm=parasail_llm(temperature=0.1, max_tokens=3500),
        max_iter=3,
        verbose=False,
        allow_delegation=False,
    )

    robot_ctx = json.dumps(robot, indent=1)[:2500]
    samples = "\n".join(cand.samples)
    others_ctx = ("\nOther incidents in the same cell (for timing context; do not investigate them):\n" + "\n".join("  - " + o for o in others)) if others else ""
    research_task = Task(
        description=(
            f"Incident {cand.id}: {tri.title}\n"
            f"Subsystem: {tri.subsystem}. Severity (triage): {tri.severity}. Suspected codes: {', '.join(tri.suspected_codes) or 'none'}.\n"
            f"Occurrences: {cand.count} between {cand.first_ts} and {cand.last_ts}. Sources: {', '.join(cand.sources)}.\n"
            f"Representative log lines:\n{samples}\n\n"
            f"Robot cell context:\n{robot_ctx}\n{others_ctx}\n\n"
            f"Suggested queries (improve them if you can): {tri.search_queries}\n\n"
            "Use you_search for 2-3 queries, then you_read the 2-3 most authoritative results (vendor docs first, then GitHub issues, then forums). "
            "Collect 3-6 pieces of evidence. Each quote must be verbatim text from a page you read, at most 60 words."
        ),
        expected_output="JSON matching EvidenceList: queries_used and a list of evidence {url,title,quote,why_relevant}.",
        agent=researcher,
        output_pydantic=EvidenceList,
    )
    diagnose_task = Task(
        description=(
            f"Diagnose incident {cand.id} ({tri.title}) using the log lines, the robot cell context and ONLY the evidence gathered by the researcher.\n"
            f"Representative log lines:\n{samples}\n{others_ctx}\n"
            "Rank the likely causes (most likely first) with a confidence in [0,1]; for each cause list the evidence URLs that support it. "
            "Consider the electrical and timing context from the robot cell description (e.g. shared power, other systems failing at the same second). "
            "Set verdict: 'exorcise' if the team must act now, 'watch' if it should be monitored, 'benign' if this is a known harmless message. "
            "Give 3-6 concrete fix_steps an on-site technician can perform tonight."
        ),
        expected_output="JSON matching Diagnosis.",
        agent=diagnostician,
        context=[research_task],
        output_pydantic=Diagnosis,
    )
    return Crew(agents=[researcher, diagnostician], tasks=[research_task, diagnose_task], process=Process.sequential, verbose=False)


def enforce_citations(diag: Diagnosis, evidence: EvidenceList) -> Diagnosis:
    """A cause may only cite URLs the researcher actually produced. Uncited causes lose confidence."""
    allowed = {e.url.rstrip("/") for e in evidence.evidence}
    for c in diag.causes:
        kept = [u for u in c.evidence_urls if u.rstrip("/") in allowed]
        if not kept and c.evidence_urls:
            c.confidence = round(c.confidence * 0.5, 2)
        c.evidence_urls = kept
    diag.causes.sort(key=lambda c: -c.confidence)
    return diag


# ---------------------------------------------------------------- field tech crew (One)


class ActionResult(BaseModel):
    kind: str
    ok: bool
    url: str | None = None
    note: str = ""


class ActionResults(BaseModel):
    results: list[ActionResult]


def one_mcp() -> MCPServerStdio:
    env = {"ONE_SECRET": settings.one_secret, "ONE_PERMISSIONS": "write", "PATH": os.environ.get("PATH", "")}
    if settings.one_connection_keys:
        env["ONE_CONNECTION_KEYS"] = settings.one_connection_keys
    return MCPServerStdio(command="npx", args=["-y", "@withone/mcp"], env=env, cache_tools_list=True)


def field_crew(actions: list[Action], observer: Callable[[str, dict], None] | None = None) -> Crew:
    """The Field Tech executes approved actions. Its tools call One's MCP server (find_one_actions -> execute_one_action)
    and return One's real response, which the flow records through `observer` (so a reported URL is never invented)."""
    tools = make_action_tools(observer)
    tech = Agent(
        role="Field Technician (actions)",
        goal="Carry out the approved containment actions in the team's real tools: post the Slack alert and open the GitHub issue, then report exactly what the tools returned.",
        backstory="You operate the lab's Slack and GitHub through One. You post the approved text verbatim and never claim a result the tool did not return.",
        llm=parasail_llm(temperature=0.0, max_tokens=2500),
        tools=tools,
        max_iter=6,
        verbose=False,
        allow_delegation=False,
    )
    payload = [a.model_dump(include={"kind", "title", "body"}) for a in actions]
    wanted = ", ".join(a.kind for a in actions)
    task = Task(
        description=(
            f"Approved actions to carry out now ({wanted}):\n{json.dumps(payload, indent=1, ensure_ascii=False)}\n\n"
            "For a slack_alert call post_slack_alert with the body verbatim. For a github_issue call open_github_issue with the title and body verbatim. "
            "Call each tool exactly once per approved action. Then report one entry per action with ok, url and note copied from the tool's JSON result."
        ),
        expected_output="JSON matching ActionResults: one entry per action with kind, ok, url, note.",
        agent=tech,
        output_pydantic=ActionResults,
    )
    return Crew(agents=[tech], tasks=[task], process=Process.sequential, verbose=False)


DIAGNOSE_SYSTEM = (
    "You are a senior robotics integrator diagnosing one incident from log lines, the robot cell context and a list of researched evidence. "
    "Rank likely causes with confidence in [0,1]; each cause may only cite URLs from the evidence list. Set verdict exorcise/watch/benign and give 3-6 concrete fix steps."
)


def diagnose_direct(cand: IncidentCandidate, tri: TriagedIncident, robot: dict, evidence: EvidenceList, others: list[str] | None = None) -> Diagnosis:
    """Fallback when the Diagnostician agent's output cannot be parsed: same reasoning, server-enforced schema."""
    user = (
        f"Incident {cand.id}: {tri.title}\nSubsystem: {tri.subsystem}. Occurrences: {cand.count} between {cand.first_ts} and {cand.last_ts}.\n"
        f"Log lines:\n" + "\n".join(cand.samples) + f"\n\nRobot cell:\n{json.dumps(robot, indent=1)[:2500]}\n"
        + ("Other incidents in the same cell:\n" + "\n".join("  - " + o for o in others) + "\n" if others else "")
        + "\nEvidence:\n" + json.dumps([e.model_dump() for e in evidence.evidence], ensure_ascii=False)[:6000]
    )
    d = parasail.chat_json(DIAGNOSE_SYSTEM, user, Diagnosis, max_tokens=3000)
    d.incident_id = cand.id
    return d
