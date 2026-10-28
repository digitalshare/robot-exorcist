"""ExorcismFlow: ingest -> cluster -> triage -> investigate (N crews) -> correlate -> (approval) -> act.
Every step publishes events to an EventBus so the console and the CLI see the same thing."""
from __future__ import annotations

import asyncio
import json
import threading
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable

from crewai.flow.flow import Flow, listen, start

from . import parasail
from .cluster import build_candidates
from .config import settings
from .crew import enforce_citations, field_crew, investigation_crew, ActionResults
from .logs import LogEvent, load_scenario
from .schemas import Action, Diagnosis, EvidenceList, IncidentCandidate, RunState, TriageResult, TriagedIncident, Verdict


class EventBus:
    """Thread-safe append-only log of events with asyncio subscribers (for WebSockets)."""

    def __init__(self):
        self.events: list[dict] = []
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()
        self.printer: Callable[[dict], None] | None = None

    def emit(self, type_: str, **payload: Any) -> None:
        ev = {"seq": len(self.events), "t": time.time(), "type": type_, **payload}
        with self._lock:
            self.events.append(ev)
            subs = list(self._subs)
        if self.printer:
            self.printer(ev)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:
                pass

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(l, qq) for l, qq in self._subs if qq is not q]


TRIAGE_SYSTEM = (
    "You are the triage lead of a robotics on-call swarm. You receive clustered log incidents from one robot cell and decide "
    "which deserve an investigation. You know common robotics error codes and which warnings are harmless noise. "
    "Write search queries a human expert would type to find the vendor documentation or a forum thread for each fault."
)

CORRELATE_SYSTEM = (
    "You are the incident commander of a robotics on-call swarm. Several investigators have each diagnosed one incident. "
    "Your job is to look across them: do the timestamps line up? Do they share a cause (power, network, a single failing component, "
    "a bad deploy)? Which are false alarms? Produce one verdict the on-site technician can act on, and draft the Slack alert and the "
    "GitHub issue. The GitHub issue body is Markdown with sections: Summary, Timeline, Evidence (as links), Fix checklist (- [ ] items), "
    "Open questions. The Slack alert is 4-8 short lines with the headline, affected systems, root cause confidence, the first fix step, "
    "and 'details in the GitHub issue'. Never invent evidence; use only the URLs provided."
)


class ExorcismFlow(Flow[RunState]):
    """CrewAI Flow. State is a RunState (pydantic)."""

    def __init__(self, scenario: str, bus: EventBus, auto: bool = False, max_incidents: int = 5, skip_actions: bool = False, replay_delay: float = 0.0):
        super().__init__()
        self.scenario = scenario
        self.bus = bus
        self.auto = auto
        self.max_incidents = max_incidents
        self.skip_actions = skip_actions
        self.replay_delay = replay_delay
        self.robot: dict = {}
        self.events: list[LogEvent] = []
        self.approval = threading.Event()
        self.approved_kinds: set[str] = set()

    # -- helpers
    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self.state, k, v)

    def _status(self, s: str):
        self.state.status = s
        self.bus.emit("status", status=s)

    # -- steps
    @start()
    def ingest(self):
        self.state.run_id = self.state.run_id or uuid.uuid4().hex[:8]
        self.state.scenario = self.scenario
        self._status("ingesting")
        self.robot, self.events = load_scenario(self.scenario)
        self.state.robot = self.robot
        self.state.events_total = len(self.events)
        self.bus.emit("robot", robot=self.robot)
        for e in self.events:
            self.bus.emit("log", event=e.to_dict())
            if self.replay_delay:
                time.sleep(self.replay_delay)
        return len(self.events)

    @listen(ingest)
    def cluster(self, _n: int):
        self._status("clustering")
        cands = build_candidates(self.events, parasail.embed)
        self.state.candidates = cands
        self.bus.emit("candidates", candidates=[c.model_dump() for c in cands], embed_model=settings.parasail_embed_model)
        return cands

    @listen(cluster)
    def triage(self, cands: list[IncidentCandidate]):
        self._status("triaging")
        if not cands:
            self.state.triage = []
            return []
        user = (
            f"Robot cell:\n{json.dumps(self.robot, indent=1)[:3000]}\n\n"
            f"Incident candidates (clustered from {self.state.events_total} log lines):\n"
            + "\n\n".join(
                f"id={c.id} system={c.system} level={c.level} count={c.count} span={c.first_ts}..{c.last_ts} sources={c.sources} codes={c.codes}\n"
                + "\n".join("  " + s for s in c.samples)
                for c in cands
            )
            + "\n\nReturn one entry per candidate id (keep the ids). Mark at most "
            f"{self.max_incidents} as 'investigate'; mark known-harmless chatter as 'watch'."
        )
        result = parasail.chat_json(TRIAGE_SYSTEM, user, TriageResult, max_tokens=3000)
        by_id = {t.id: t for t in result.incidents}
        tri = [by_id[c.id] for c in cands if c.id in by_id]
        self.state.triage = tri
        self.bus.emit("triage", triage=[t.model_dump() for t in tri], model=settings.parasail_model)
        return tri

    @listen(triage)
    async def investigate(self, tri: list[TriagedIncident]):
        self._status("investigating")
        cands = {c.id: c for c in self.state.candidates}
        todo = [t for t in tri if t.decision == "investigate"][: self.max_incidents]
        sem = asyncio.Semaphore(max(1, settings.concurrency))

        def observer(kind: str, payload: dict):
            self.bus.emit(kind, **payload)

        async def one(t: TriagedIncident):
            async with sem:
                self.bus.emit("investigating", incident_id=t.id, title=t.title)
                try:
                    others = [
                        f"{o.id} [{cands[o.id].system}] {o.title}: {cands[o.id].count}x between {cands[o.id].first_ts[11:19]} and {cands[o.id].last_ts[11:19]}"
                        for o in tri if o.id != t.id and o.id in cands
                    ]
                    crew = investigation_crew(cands[t.id], t, self.robot, observer, others)
                    out = await asyncio.to_thread(crew.kickoff)
                    ev: EvidenceList | None = None
                    diag: Diagnosis | None = None
                    for task_out in out.tasks_output:
                        p = task_out.pydantic
                        if isinstance(p, EvidenceList):
                            ev = p
                        elif isinstance(p, Diagnosis):
                            diag = p
                    if ev is None:
                        ev = EvidenceList(evidence=[])
                    if diag is None:
                        raise RuntimeError("diagnostician returned no Diagnosis")
                    diag.incident_id = t.id
                    diag = enforce_citations(diag, ev)
                    self.state.evidence[t.id] = ev
                    self.state.diagnoses[t.id] = diag
                    self.bus.emit("evidence", incident_id=t.id, evidence=ev.model_dump())
                    self.bus.emit("diagnosis", incident_id=t.id, diagnosis=diag.model_dump())
                except Exception as e:
                    self.bus.emit("investigation_failed", incident_id=t.id, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:])

        await asyncio.gather(*(one(t) for t in todo))
        return list(self.state.diagnoses.values())

    @listen(investigate)
    def correlate(self, diags: list[Diagnosis]):
        self._status("correlating")
        if not diags:
            self.state.verdict = Verdict(headline="No incidents warranted investigation", shared_root_cause=None, confidence=0.5, narrative="Nothing above WARN clustered into an actionable incident.", recommended_fix=[], actions=[])
            self.bus.emit("verdict", verdict=self.state.verdict.model_dump())
            return self.state.verdict
        cands = {c.id: c for c in self.state.candidates}
        tri = {t.id: t for t in self.state.triage}
        blocks = []
        for d in diags:
            c, t = cands[d.incident_id], tri[d.incident_id]
            ev = self.state.evidence.get(d.incident_id)
            blocks.append(
                f"### {d.incident_id}: {t.title}\nsystem={c.system} count={c.count} span={c.first_ts}..{c.last_ts}\n"
                f"verdict={d.verdict} severity={d.severity}\nsummary: {d.summary}\n"
                + "causes:\n" + "\n".join(f"  - ({x.confidence:.2f}) {x.cause} [{', '.join(x.evidence_urls)}]" for x in d.causes)
                + "\nfix_steps: " + json.dumps(d.fix_steps)
                + "\nevidence: " + json.dumps([{"url": e.url, "title": e.title, "quote": e.quote} for e in (ev.evidence if ev else [])])[:2500]
            )
        watched = [f"{t.id}: {t.title} ({t.why})" for t in self.state.triage if t.decision != "investigate"]
        user = (
            f"Robot cell:\n{json.dumps(self.robot, indent=1)[:3000]}\n\nScenario folder: {self.scenario}\nGenerated at: {datetime.now().isoformat(timespec='seconds')}\n\n"
            + "\n\n".join(blocks)
            + ("\n\nNot investigated (triage said watch):\n" + "\n".join(watched) if watched else "")
            + "\n\nProduce the Verdict. Include exactly two actions: one slack_alert and one github_issue."
        )
        verdict = parasail.chat_json(CORRELATE_SYSTEM, user, Verdict, max_tokens=4500)
        self.state.verdict = verdict
        self.bus.emit("verdict", verdict=verdict.model_dump(), model=settings.parasail_model)
        return verdict

    @listen(correlate)
    def act(self, verdict: Verdict):
        if not verdict.actions:
            self._status("done")
            return verdict
        self._status("awaiting_approval")
        if self.skip_actions:
            self.approve(set())
        elif self.auto:
            self.approve({a.kind for a in verdict.actions})
        self.approval.wait()
        approved = [a for a in verdict.actions if a.kind in self.approved_kinds]
        for a in verdict.actions:
            if a.kind not in self.approved_kinds:
                a.status = "skipped"
        if not approved:
            self._status("done")
            self.bus.emit("actions", actions=[a.model_dump() for a in verdict.actions])
            return verdict
        self._status("acting")
        for a in approved:
            a.status = "approved"
        self.bus.emit("actions", actions=[a.model_dump() for a in verdict.actions])
        results: dict[str, dict] = {}

        def on_action(kind: str, payload: dict):
            # the tool's own result is the record of truth
            self.bus.emit(kind, **payload)
            if kind == "action_result" and payload["kind"] not in results:
                results[payload["kind"]] = {"ok": payload["ok"], "url": payload.get("url"), "note": payload.get("note", ""), "via": "field_tech_agent"}

        try:
            field_crew(approved, on_action).kickoff()
        except Exception as e:
            self.bus.emit("field_agent_failed", error=f"{type(e).__name__}: {e}")
        # fallback: deterministic executor through the same One MCP tools
        from . import one_exec

        for a in approved:
            r = results.get(a.kind)
            if not r or not r.get("ok"):
                try:
                    fr = one_exec.run(one_exec.execute(a.kind, a.title, a.body))
                    results[a.kind] = {"ok": fr["ok"], "url": fr.get("url"), "note": fr.get("note") or ("" if fr["ok"] else json.dumps(fr.get("raw"))[:300]), "via": "one_exec"}
                except Exception as e:
                    results[a.kind] = {"ok": False, "url": None, "note": f"{type(e).__name__}: {e}", "via": "one_exec"}
            r = results[a.kind]
            a.status = "done" if r["ok"] else "failed"
            a.result_url = r.get("url")
            a.result_note = (r.get("via") or "") + (f": {r['note']}" if r.get("note") else "")
        self.bus.emit("actions", actions=[a.model_dump() for a in verdict.actions])
        self._status("done")
        return verdict

    # -- approval gate (called from the server or by --auto)
    def approve(self, kinds: set[str]):
        self.approved_kinds = set(kinds)
        self.approval.set()


def run_flow(scenario: str, bus: EventBus, auto: bool, skip_actions: bool = False) -> ExorcismFlow:
    flow = ExorcismFlow(scenario, bus, auto=auto, skip_actions=skip_actions)
    try:
        flow.kickoff()
    except Exception as e:
        flow.state.error = f"{type(e).__name__}: {e}"
        bus.emit("error", error=flow.state.error, trace=traceback.format_exc()[-2000:])
        flow.state.status = "error"
        bus.emit("status", status="error")
    return flow
