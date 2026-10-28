"""Pydantic models shared by the flow, the crews, the JSON-schema calls and the UI."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IncidentCandidate(BaseModel):
    id: str
    system: str
    sources: list[str]
    level: str
    count: int
    first_ts: str
    last_ts: str
    signature: str
    samples: list[str] = Field(description="Up to 5 raw representative lines")
    codes: list[str] = []


class TriagedIncident(BaseModel):
    id: str
    title: str = Field(description="Short human title, e.g. 'UR5e C204A0 protective stops on joint 3'")
    subsystem: str
    severity: Literal["low", "medium", "high", "critical"]
    decision: Literal["investigate", "watch"]
    suspected_codes: list[str] = []
    search_queries: list[str] = Field(description="2-3 web search queries that would find the vendor doc or forum thread for this fault")
    why: str = Field(description="One sentence on why this is or is not worth investigating")


class TriageResult(BaseModel):
    incidents: list[TriagedIncident]


class Evidence(BaseModel):
    url: str
    title: str = ""
    quote: str = Field(default="", description="Verbatim excerpt (<= 60 words) from the page that supports or refutes a cause")
    why_relevant: str = ""


class EvidenceList(BaseModel):
    queries_used: list[str] = []
    evidence: list[Evidence]


class Cause(BaseModel):
    cause: str
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_urls: list[str] = Field(default_factory=list, description="URLs from the evidence list that support this cause")
    reasoning: str = ""


class Diagnosis(BaseModel):
    incident_id: str = ""
    verdict: Literal["exorcise", "watch", "benign"] = Field(description="exorcise = act now, watch = monitor, benign = false alarm")
    severity: Literal["low", "medium", "high", "critical"]
    summary: str = ""
    causes: list[Cause] = Field(default_factory=list, description="Ranked, most likely first")
    fix_steps: list[str] = []
    open_questions: list[str] = []


class Action(BaseModel):
    kind: Literal["slack_alert", "github_issue"]
    title: str
    body: str
    status: Literal["proposed", "approved", "done", "failed", "skipped"] = "proposed"
    result_url: str | None = None
    result_note: str | None = None


class Verdict(BaseModel):
    headline: str = Field(description="One line a tired on-call engineer can act on")
    shared_root_cause: str | None = Field(description="If several incidents are one underlying cause, name it; otherwise null")
    linked_incident_ids: list[str] = []
    false_alarm_ids: list[str] = []
    confidence: float = Field(ge=0, le=1)
    narrative: str = Field(description="3-6 sentences tying the timeline and the evidence together")
    recommended_fix: list[str]
    actions: list[Action]


class RunState(BaseModel):
    run_id: str = ""
    scenario: str = ""
    status: str = "idle"
    robot: dict = {}
    events_total: int = 0
    candidates: list[IncidentCandidate] = []
    triage: list[TriagedIncident] = []
    evidence: dict[str, EvidenceList] = {}
    diagnoses: dict[str, Diagnosis] = {}
    verdict: Verdict | None = None
    error: str | None = None
