"""CLI: `exorcist serve` (console on :8000), `exorcist run <scenario> [--auto]`, `exorcist smoke`."""
from __future__ import annotations

import argparse
import json
import sys
import textwrap

from .config import settings


def _print_event(ev: dict) -> None:
    t = ev["type"]
    if t == "log":
        return
    if t == "status":
        print(f"\n== {ev['status']} ==")
    elif t == "candidates":
        for c in ev["candidates"]:
            print(f"  {c['id']:<7} {c['system']:<8} {c['level']:<5} x{c['count']:<3} {c['signature'][:90]}")
    elif t == "triage":
        for x in ev["triage"]:
            print(f"  {x['id']:<7} {x['decision']:<11} {x['severity']:<8} {x['title']}")
    elif t == "search":
        print(f"  [{ev['incident_id']}] search: {ev['query']}  -> {len(ev['results'])} results")
    elif t == "read":
        print(f"  [{ev['incident_id']}] read:   {ev['title'][:70]}  ({ev['url']})")
    elif t == "diagnosis":
        d = ev["diagnosis"]
        print(f"  [{ev['incident_id']}] {d['verdict'].upper()} ({d['severity']}): {d['summary']}")
        for c in d["causes"][:3]:
            print(f"      ({c['confidence']:.2f}) {c['cause']}  cites {len(c['evidence_urls'])}")
    elif t == "investigation_failed":
        print(f"  [{ev['incident_id']}] FAILED: {ev['error']}")
    elif t == "verdict":
        v = ev["verdict"]
        print(f"\n  HEADLINE: {v['headline']}\n  shared root cause: {v['shared_root_cause']}  (confidence {v['confidence']:.2f})")
        print(textwrap.indent(textwrap.fill(v["narrative"], 110), "  "))
        print("  linked:", v["linked_incident_ids"], " false alarms:", v["false_alarm_ids"])
    elif t == "actions":
        for a in ev["actions"]:
            print(f"  action {a['kind']:<13} {a['status']:<9} {a.get('result_url') or ''} {a.get('result_note') or ''}")
    elif t in ("error", "field_agent_failed"):
        print(f"  !! {t}: {ev.get('error')}")
        if ev.get("trace"):
            print(textwrap.indent(ev["trace"], "     "))


def cmd_smoke(_args) -> int:
    missing = settings.missing()
    if missing:
        print("missing in .env:", ", ".join(missing))
    ok = True
    # Parasail
    try:
        from . import parasail

        models = parasail.list_models()
        print(f"Parasail: {len(models)} models visible")
        for m in models:
            if any(k in m for k in ("qwen3-235b", "kimi", "grit", "embed", "gpt-oss-120b", "glm-5")):
                print("   ", m)
        print("  chat model:", settings.parasail_model, "->", "OK" if settings.parasail_model in models else "NOT IN LIST")
        print("  embed model:", settings.parasail_embed_model, "->", "OK" if settings.parasail_embed_model in models else "NOT IN LIST")
        vec = parasail.embed(["protective stop position deviates from path"])
        print(f"  embeddings OK (dim {len(vec[0])})")
        from pydantic import BaseModel

        class Ping(BaseModel):
            answer: str
            number: int

        p = parasail.chat_json("Answer tersely.", "Say hi and give the number 7.", Ping)
        print("  schema-locked JSON OK:", p.model_dump())
    except Exception as e:
        ok = False
        print("  Parasail FAILED:", type(e).__name__, str(e)[:300])
    # You.com
    try:
        from . import you

        res = you.search("UR5e C204A0 protective stop position deviates from path", count=3)
        print(f"You.com search OK: {len(res)} results; first: {res[0]['title'][:60] if res else '-'}")
        if res:
            page = you.contents(res[0]["url"])
            print(f"  contents OK: {page['title'][:60]} ({len(page['markdown'])} chars)")
    except Exception as e:
        ok = False
        print("  You.com FAILED:", type(e).__name__, str(e)[:300])
    # One
    try:
        from . import one_exec

        info = one_exec.run(one_exec.list_integrations())
        print("One MCP tools:", info["tools"])
        print("  integrations:", json.dumps(info["integrations"], indent=1)[:1500])
    except Exception as e:
        ok = False
        print("  One FAILED:", type(e).__name__, str(e)[:300])
    print("\nsmoke:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def cmd_run(args) -> int:
    from .flow import EventBus, run_flow

    bus = EventBus()
    bus.printer = _print_event
    flow = run_flow(args.scenario, bus, auto=args.auto)
    if args.json:
        print(flow.state.model_dump_json(indent=1))
    return 0 if flow.state.status == "done" else 1


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("exorcist.server:app", host="127.0.0.1", port=args.port, reload=False, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="exorcist", description="Robot Exorcist: a CrewAI swarm that diagnoses a possessed robot.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("smoke", help="one real call per partner").set_defaults(fn=cmd_smoke)
    r = sub.add_parser("run", help="run the flow in the terminal")
    r.add_argument("scenario", nargs="?", default="samples/haunted_cell")
    r.add_argument("--auto", action="store_true", help="approve actions without asking")
    r.add_argument("--json", action="store_true", help="dump final state as JSON")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("serve", help="web console")
    s.add_argument("--port", type=int, default=settings.port)
    s.set_defaults(fn=cmd_serve)
    args = p.parse_args(argv)
    if not args.cmd:
        args = p.parse_args(["serve"])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
