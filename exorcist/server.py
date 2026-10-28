"""FastAPI console: starts runs, streams events over WebSocket, holds the approval gate."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, settings
from .flow import EventBus, ExorcismFlow, run_flow

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="Robot Exorcist")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Run:
    def __init__(self, scenario: str, auto: bool):
        self.bus = EventBus()
        self.flow: ExorcismFlow | None = None
        self.scenario = scenario
        self.auto = auto
        self.thread = threading.Thread(target=self._go, daemon=True)

    def _go(self):
        self.flow = ExorcismFlow(self.scenario, self.bus, auto=self.auto)
        try:
            self.flow.kickoff()
        except Exception as e:
            import traceback

            self.flow.state.status = "error"
            self.bus.emit("error", error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
            self.bus.emit("status", status="error")


current: Run | None = None


class StartBody(BaseModel):
    scenario: str = "samples/haunted_cell"
    auto: bool = False


class ApproveBody(BaseModel):
    kinds: list[str]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/scenarios")
def scenarios():
    out = []
    for d in sorted((ROOT / "samples").iterdir()):
        if d.is_dir() and any(d.glob("*.log")):
            out.append({"path": f"samples/{d.name}", "name": d.name.replace("_", " ")})
    return out


@app.get("/api/config")
def config():
    return {
        "missing": settings.missing(),
        "chat_model": settings.parasail_model,
        "embed_model": settings.parasail_embed_model,
        "slack_channel": settings.slack_channel,
        "github_repo": settings.github_repo,
        "concurrency": settings.concurrency,
    }


@app.post("/api/run")
def start(body: StartBody):
    global current
    if current and current.flow and current.flow.state.status not in ("done", "error", "idle") and current.thread.is_alive():
        return JSONResponse({"error": "a run is already in progress"}, status_code=409)
    current = Run(body.scenario, body.auto)
    current.thread.start()
    return {"ok": True, "scenario": body.scenario}


@app.post("/api/approve")
def approve(body: ApproveBody):
    if not current or not current.flow:
        return JSONResponse({"error": "no run"}, status_code=404)
    current.flow.approve(set(body.kinds))
    return {"ok": True, "kinds": body.kinds}


@app.get("/api/state")
def state():
    if not current or not current.flow:
        return {"status": "idle", "events": []}
    return {"status": current.flow.state.status, "events": current.bus.events}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    loop = asyncio.get_running_loop()
    run = current
    try:
        if run is None:
            # wait until a run exists
            while current is None:
                await asyncio.sleep(0.3)
            run = current
        q = run.bus.subscribe(loop)
        # replay history first
        for ev in list(run.bus.events):
            await sock.send_json(ev)
        while True:
            ev = await q.get()
            await sock.send_json(ev)
            if run is not current:  # a new run started: client should reconnect
                await sock.send_json({"type": "reset"})
                break
    except WebSocketDisconnect:
        pass
    finally:
        try:
            run.bus.unsubscribe(q)  # type: ignore[name-defined]
        except Exception:
            pass
