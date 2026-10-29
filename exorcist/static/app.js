const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { candidates: {}, triage: {}, steps: {}, evidence: {}, diagnoses: {}, verdict: null, actions: [], selected: null, status: "idle", logCount: 0, robot: null, events: [] };
let ws = null;

const STAGES = ["ingesting", "clustering", "triaging", "investigating", "correlating", "awaiting_approval", "acting"];
const STAGE_ICON = { ingesting: "logs", clustering: "cluster", triaging: "triage", investigating: "search", correlating: "link", awaiting_approval: "check", acting: "megaphone" };
function initPipeline() { document.querySelectorAll("#pipeline .stage").forEach((el) => (el.querySelector(".ico").innerHTML = ICON[STAGE_ICON[el.dataset.stage]])); }
function renderPipeline(status) {
  const idx = STAGES.indexOf(status);
  document.querySelectorAll("#pipeline .stage").forEach((el, i) => {
    el.classList.remove("done", "active");
    if (status === "done") el.classList.add("done");
    else if (status === "error" || status === "idle") return;
    else if (i < idx) el.classList.add("done");
    else if (i === idx) el.classList.add("active");
  });
}

// ---- 3D story overlay (module loaded on demand) ----
let story = null;
const STORY_EVENTS = new Set(["diagnosis", "verdict", "actions", "investigating", "search", "read"]);
function storyEvent(ev) {
  // the story only needs to know which system an incident belongs to
  if (ev.incident_id) { const c = state.candidates[ev.incident_id]; return { ...ev, system: c ? c.system : null }; }
  return ev;
}
async function openStory(opts = {}) {
  const overlay = $("#story-overlay"), mount = $("#story-mount");
  overlay.hidden = false;
  const scenario = state.scenario || $("#scenario").value;
  $("#story-scn").textContent = scenario.replace("samples/", "").replace("_", " ");
  const { createStory } = await import("/static/story.js");
  if (story) story.dispose();
  story = createStory(mount);
  const data = await (await fetch(`/api/scenario?path=${encodeURIComponent(scenario)}`)).json();
  story.load(data);
  if (opts.skipReplay) story.seek(1);
  // chapters already reached by the current run (only if that run is this scenario)
  const sameRun = state.scenario === scenario && state.status !== "idle";
  if (sameRun) for (const id of Object.keys(state.diagnoses)) story.applyRunEvent(storyEvent({ type: "diagnosis", incident_id: id, diagnosis: state.diagnoses[id] }));
  if (sameRun && state.verdict) story.applyRunEvent({ type: "verdict", verdict: state.verdict });
  if (sameRun && state.actions && state.actions.length) story.applyRunEvent({ type: "actions", actions: state.actions });
  if (!opts.skipReplay) story.play();
}
function closeStory() { $("#story-overlay").hidden = true; if (story) { story.dispose(); story = null; } }

async function init() {
  initPipeline();
  $("#story-btn").onclick = () => openStory();
  $("#story-close").onclick = closeStory;
  const snd = window.exorcistSound;
  const soundBtn = $("#sound-btn"); soundBtn.textContent = snd && snd.enabled ? "🔊" : "🔇";
  soundBtn.onclick = () => { soundBtn.textContent = snd.toggle() ? "🔊" : "🔇"; };
  $("#auto-btn").onclick = () => (autopilot.stage === "off" ? startAutopilot() : stopAutopilot());
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "Escape") { closeStory(); stopAutopilot(); }
    if (e.key === "p" || e.key === "P") autopilot.stage === "off" ? startAutopilot() : stopAutopilot();
  });
  $("#story-mount").addEventListener("story:ended", () => { if (autopilot.stage === "intro") { closeStory(); autopilot.stage = "run"; startRun(); } });
  const sc = await (await fetch("/api/scenarios")).json();
  $("#scenario").innerHTML = sc.map((s) => `<option value="${esc(s.path)}">${esc(s.name)}</option>`).join("");
  const cfg = await (await fetch("/api/config")).json();
  $("#cfg-model").textContent = cfg.chat_model;
  $("#cfg-targets").textContent = `${cfg.slack_channel} · ${cfg.github_repo}`;
  if (cfg.missing.length) { setStatus("error"); $("#verdict").innerHTML = `<p class="err">Missing in .env: ${esc(cfg.missing.join(", "))}</p>`; }
  $("#start").onclick = startRun;
  // if a run exists already (page refresh), reattach
  const st = await (await fetch("/api/state")).json();
  if (st.status !== "idle") { connect(); }
}

function seance() {
  const el = $("#seance"); $("#seance-sub").textContent = ($("#scenario").selectedOptions[0] || {}).text || "";
  el.hidden = false; el.classList.remove("out");
  setTimeout(() => el.classList.add("out"), 1700); setTimeout(() => (el.hidden = true), 2300);
}

async function startRun() {
  resetUI();
  seance();
  state.scenario = $("#scenario").value;
  const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: state.scenario, auto: $("#auto").checked }) });
  if (!r.ok) { const e = await r.json(); alert(e.error || "failed"); return; }
  $("#start").disabled = true;
  connect();
}

function connect() {
  if (ws) { try { ws.close(); } catch {} }
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (m) => handle(JSON.parse(m.data));
  ws.onclose = () => { if (!["done", "error"].includes(state.status)) setTimeout(connect, 800); };
}

function resetUI() {
  Object.assign(state, { candidates: {}, triage: {}, steps: {}, evidence: {}, diagnoses: {}, verdict: null, actions: [], selected: null, status: "idle", logCount: 0, events: [] });
  $("#bursts").innerHTML = "";
  $("#logs").innerHTML = ""; $("#cell").innerHTML = ""; $("#incidents").innerHTML = ""; $("#investigation").innerHTML = ""; $("#verdict").innerHTML = ""; $("#actions").innerHTML = ""; $("#log-count").textContent = "";
}

function setStatus(s) {
  state.status = s;
  renderPipeline(s);
  const el = $("#status"); el.textContent = s.replace("_", " ");
  el.className = "status " + (["done", "error", "awaiting_approval", "idle"].includes(s) ? s : "running");
  if (["done", "error"].includes(s)) $("#start").disabled = false;
  if (state.actions && state.actions.length) renderActions(); // approval buttons depend on status
}

const recentErrors = [];
function onLogEffects(e) {
  if (e.level !== "ERROR") return;
  const t = performance.now(); recentErrors.push({ t, system: e.system });
  while (recentErrors.length && t - recentErrors[0].t > 1000) recentErrors.shift();
  const snd = window.exorcistSound;
  if (/Protective Stop|Hardware Error|Timeout waiting|collision/i.test(e.text)) snd && snd.thunk();
  if (recentErrors.length >= 3) { const box = $("#logs"); box.classList.remove("glitch"); void box.offsetWidth; box.classList.add("glitch"); }
  if (new Set(recentErrors.map((r) => r.system)).size >= 2) snd && snd.hum();
}

function handle(ev) {
  if (ev.type === "robot") state.scenario = state.scenario || $("#scenario").value;
  if (ev.type === "log") { state.events.push(ev.event); onLogEffects(ev.event); }
  if (ev.type === "diagnosis") window.exorcistSound && window.exorcistSound.chime();
  if (ev.type === "verdict") { window.exorcistSound && window.exorcistSound.gong(); if (autopilot.stage === "run") { autopilot.stage = "verdict"; openStory({ skipReplay: true }); } }
  if (ev.type === "actions" && ev.actions.some((a) => a.status === "done") && ev.actions.every((a) => ["done", "skipped", "failed"].includes(a.status))) window.exorcistSound && window.exorcistSound.sparkle();
  if (ev.type === "status" && ["done", "error"].includes(ev.status)) stopAutopilot();
  if (story && STORY_EVENTS.has(ev.type)) story.applyRunEvent(storyEvent(ev));
  switch (ev.type) {
    case "reset": resetUI(); connect(); break;
    case "status": setStatus(ev.status); break;
    case "robot": state.robot = ev.robot; renderRobot(); break;
    case "log": appendLog(ev.event); break;
    case "candidates": ev.candidates.forEach((c) => (state.candidates[c.id] = c)); $("#inc-hint").textContent = `${ev.candidates.length} clusters · ${ev.embed_model}`; renderIncidents(); renderCell(); renderBursts(); break;
    case "triage": ev.triage.forEach((t) => (state.triage[t.id] = t)); renderIncidents(); renderCell(); renderBursts(); break;
    case "investigating": step(ev.incident_id, { kind: "start", title: ev.title }); if (!state.selected) select(ev.incident_id); break;
    case "search": step(ev.incident_id, { kind: "search", query: ev.query, results: ev.results }); break;
    case "read": step(ev.incident_id, { kind: "read", url: ev.url, title: ev.title, chars: ev.chars }); break;
    case "evidence": state.evidence[ev.incident_id] = ev.evidence; renderInvestigation(); break;
    case "diagnosis": state.diagnoses[ev.incident_id] = ev.diagnosis; renderIncidents(); renderInvestigation(); renderCell(); break;
    case "investigation_failed": step(ev.incident_id, { kind: "fail", error: ev.error }); break;
    case "note": step(ev.incident_id, { kind: "note", text: ev.text }); break;
    case "verdict": state.verdict = ev.verdict; renderVerdict(); renderCell(); renderBursts(); break;
    case "actions": state.actions = ev.actions; renderActions(); break;
    case "error": $("#verdict").innerHTML += `<p class="err">${esc(ev.error)}\n${esc(ev.trace || "")}</p>`; break;
    case "field_agent_failed": $("#act-hint").textContent = "field agent failed, using deterministic One executor"; break;
  }
}

function renderRobot() {
  const r = state.robot || {};
  $("#robot").innerHTML = `<b>${esc(r.cell || "")}</b> — ${esc(r.power || "")}`;
  renderCell();
}

function glyph(name, x, y, scale = 1) {
  const inner = (ICON[name] || ICON.robot).replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
  return `<g class="glyph" transform="translate(${x},${y}) scale(${scale})">${inner}</g>`;
}

// The cell as a circuit: one PSU feeding every system. Nodes pick up incident counts and severity as the run
// progresses; when the verdict names a shared root cause the wires to the linked systems light up.
function renderCell() {
  const r = state.robot || {}; const systems = r.systems || [];
  if (!systems.length) { $("#cell").innerHTML = ""; return; }
  const W = 420, rowH = 44, H = Math.max(systems.length * rowH + 10, 70);
  const bySys = {};
  for (const c of Object.values(state.candidates)) {
    const t = state.triage[c.id], d = state.diagnoses[c.id];
    const b = (bySys[c.system] ||= { count: 0, sev: "", ids: [] });
    if (c.level === "ERROR" || c.level === "FATAL" || (t && t.decision === "investigate")) b.count += c.count;
    const sev = d ? d.severity : t ? t.severity : "";
    const rank = { critical: 4, high: 3, medium: 2, low: 1, "": 0 };
    if (rank[sev] > rank[b.sev]) b.sev = sev;
    b.ids.push(c.id);
  }
  const v = state.verdict; const linked = new Set(v ? v.linked_incident_ids : []);
  const shared = !!(v && v.shared_root_cause);
  let h = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Robot cell power diagram">`;
  const psuY = H / 2;
  h += `<rect class="psu ${shared ? "hot" : ""}" x="8" y="${psuY - 22}" width="92" height="44" rx="7"/>${glyph(shared ? "bolt" : "psu", 16, psuY - 12, 1)}<text class="lbl" x="44" y="${psuY - 2}">shared</text><text class="sub" x="44" y="${psuY + 11}">power</text>`;
  systems.forEach((sys, i) => {
    const y = 8 + i * rowH + rowH / 2;
    const b = bySys[sys.id] || { count: 0, sev: "", ids: [] };
    const isLinked = shared && b.ids.some((id) => linked.has(id));
    h += `<path class="wire ${isLinked ? "hot" : ""}" d="M100 ${psuY} C 130 ${psuY}, 130 ${y}, 160 ${y}"/>`;
    h += `<rect class="node ${b.sev ? "sev-" + b.sev : ""} ${isLinked ? "linked" : ""}" x="160" y="${y - 18}" width="${W - 168}" height="36" rx="7"/>`;
    h += glyph(systemIcon(sys.kind, sys.id), 168, y - 12, 1);
    const kind = String(sys.kind || ""); const short = kind.length > 30 ? kind.slice(0, 29) + "…" : kind;
    h += `<text class="lbl" x="196" y="${y - 2}">${esc(sys.id)}</text><text class="sub" x="196" y="${y + 11}">${esc(short)}</text>`;
    if (b.count) h += `<text class="cnt" x="${W - 14}" y="${y + 4}" text-anchor="end">${b.count} faults</text>`;
    if (isLinked) h += glyph("ghost", W - 96, y - 10, 0.8);
  });
  h += `</svg>`;
  $("#cell").innerHTML = h;
}

function appendLog(e) {
  state.logCount++;
  const d = document.createElement("div");
  d.innerHTML = `<span class="ts">${esc(e.ts.slice(11))}</span> <span class="${esc(e.level)}">${esc(e.level.padEnd(5))}</span> <span class="src">${esc(e.system)}/${esc(e.source)}</span> <span class="${esc(e.level)}">${esc(e.text)}</span>`;
  const box = $("#logs"); box.appendChild(d); box.scrollTop = box.scrollHeight;
  $("#log-count").textContent = `${state.logCount} lines`;
}

function renderIncidents() {
  const ids = Object.keys(state.candidates);
  $("#incidents").innerHTML = ids.map((id) => {
    const c = state.candidates[id], t = state.triage[id], d = state.diagnoses[id];
    const title = t ? t.title : c.signature.slice(0, 80);
    const sysKind = ((state.robot || {}).systems || []).find((x) => x.id === c.system);
    const sIcon = icon(systemIcon(sysKind ? sysKind.kind : "", c.system));
    const badges = [t ? `<span class="badge ${t.severity}">${t.severity}</span>` : "", t ? `<span class="badge ${t.decision}">${t.decision}</span>` : "", d ? `<span class="badge ${d.verdict}">${d.verdict}</span>` : ""].join(" ");
    return `<div class="card ${state.selected === id ? "sel" : ""}" data-id="${id}"><div class="top"><span class="title">${sIcon}${esc(title)}</span><span>${badges}</span></div><div class="meta">${id} · ${esc(c.system)} · ${esc(c.level)} ×${c.count} · ${esc(c.first_ts.slice(11, 19))}–${esc(c.last_ts.slice(11, 19))}${c.codes.length ? " · " + esc(c.codes.join(", ")) : ""}</div>${t ? `<div class="meta">${esc(t.why)}</div>` : ""}</div>`;
  }).join("");
  document.querySelectorAll(".card").forEach((el) => (el.onclick = () => select(el.dataset.id)));
}

function select(id) { state.selected = id; renderIncidents(); renderInvestigation(); }
function step(id, s) {
  const arr = (state.steps[id] ||= []);
  const key = s.kind === "search" ? "q:" + s.query : s.kind === "read" ? "u:" + s.url : null;
  const dup = key && arr.find((x) => x.key === key);
  if (dup) { dup.n = (dup.n || 1) + 1; } else { arr.push(Object.assign(s, { key })); } if (state.selected === id || !state.selected) { state.selected = id; renderInvestigation(); renderIncidents(); } }

function renderInvestigation() {
  const id = state.selected; if (!id) return;
  const t = state.triage[id], c = state.candidates[id], steps = state.steps[id] || [], d = state.diagnoses[id], ev = state.evidence[id];
  $("#inv-hint").textContent = `${id} · Researcher → Diagnostician`;
  let h = `<div class="meta muted" style="font-family:var(--mono);font-size:11px;margin-bottom:6px">${(c.samples || []).slice(0, 3).map(esc).join("<br>")}</div>`;
  if (!steps.length && !d) h += `<p class="muted">${t && t.decision === "watch" ? "Triage marked this as watch-only; not investigated." : "Waiting for an investigator…"}</p>`;
  for (const s of steps) {
    if (s.kind === "start") h += `<div class="step">${icon("cluster")} Investigation crew started: Researcher → Diagnostician</div>`;
    if (s.kind === "search") h += `<div class="step search">${icon("search")} <span class="q">${esc(s.query)}</span>${s.n > 1 ? ` <span class="res">×${s.n}</span>` : ""}<div class="res">${s.results.slice(0, 4).map((r) => `<a href="${esc(r.url)}" target="_blank">${esc(r.title || r.url).slice(0, 70)}</a>`).join(" · ")}</div></div>`;
    if (s.kind === "read") h += `<div class="step read">${icon("book")} <a href="${esc(s.url)}" target="_blank">${esc(s.title || hostOf(s.url)).slice(0, 90)}</a> <span class="res">${s.chars} chars${s.n > 1 ? ` ×${s.n}` : ""}</span></div>`;
    if (s.kind === "fail") h += `<div class="step err">✖ ${esc(s.error)}</div>`;
    if (s.kind === "note") h += `<div class="step muted">ℹ ${esc(s.text)}</div>`;
  }
  if (d) {
    h += `<div class="diag"><h3>${icon("brain", "kind-ico")} <span class="badge ${d.verdict}">${d.verdict}</span> <span class="badge ${d.severity}">${d.severity}</span> ${esc(d.summary)}</h3>`;
    for (const cause of d.causes) {
      h += `<div class="cause"><div><b>${esc(cause.cause)}</b> <span class="muted">${Math.round(cause.confidence * 100)}%</span></div><div class="bar"><i style="width:${Math.round(cause.confidence * 100)}%"></i></div><div class="muted" style="font-size:12px;margin-top:4px">${esc(cause.reasoning)}</div><div class="cites">${cause.evidence_urls.map((u) => `<a href="${esc(u)}" target="_blank">${esc(hostOf(u))}</a>`).join("")}</div></div>`;
    }
    h += `<div><b>${icon("check")} Fix tonight</b><ol class="fix">${d.fix_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>`;
    if (ev && ev.evidence.length) h += `<details style="margin-top:8px"><summary class="muted">${ev.evidence.length} quotes collected</summary>${ev.evidence.map((e) => `<div class="step"><a href="${esc(e.url)}" target="_blank">${esc(e.title)}</a><div class="muted">“${esc(e.quote)}”</div></div>`).join("")}</details>`;
    h += `</div>`;
  }
  $("#investigation").innerHTML = h;
}

function hostOf(u) { try { return new URL(u).host.replace("www.", ""); } catch { return u; } }

function renderVerdict() {
  const v = state.verdict; if (!v) return;
  $("#verdict").innerHTML = `<div class="verdict"><h3>${esc(v.headline)}</h3>${v.shared_root_cause ? `<div class="rc">${icon("ghost")} <b>One ghost, not ${Object.keys(state.diagnoses).length || "many"}:</b> ${esc(v.shared_root_cause)} <span class="muted">(${Math.round(v.confidence * 100)}% confidence)</span></div>` : `<div class="rc">No shared root cause <span class="muted">(${Math.round(v.confidence * 100)}%)</span></div>`}<p>${esc(v.narrative)}</p><p class="muted">linked: ${v.linked_incident_ids.join(", ") || "—"} · false alarms: ${v.false_alarm_ids.join(", ") || "—"}</p><b>Recommended fix</b><ol class="fix">${v.recommended_fix.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>`;
}

function renderActions() {
  const acts = state.actions || [];
  const pending = acts.some((a) => a.status === "proposed") && state.status === "awaiting_approval";
  let h = pending ? `<div class="approve"><button id="approve-all">Approve all</button>${acts.map((a) => `<button class="ghost approve-one" data-kind="${a.kind}">Only ${a.kind.replace("_", " ")}</button>`).join("")}<button class="ghost" id="approve-none">Skip</button></div>` : "";
  h += acts.map((a) => `<div class="action"><div class="top"><b>${a.kind === "slack_alert" ? icon("slack", "kind-ico") + " Slack alert" : icon("github", "kind-ico") + " GitHub issue"} <span class="muted">${esc(a.title)}</span></b><span class="st ${a.status}">${a.status}${a.result_url ? ` · <a href="${esc(a.result_url)}" target="_blank">open</a>` : ""}</span></div>${a.result_note ? `<div class="muted" style="font-size:11px">${esc(a.result_note)}</div>` : ""}<pre>${esc(a.body)}</pre></div>`).join("");
  $("#actions").innerHTML = h;
  $("#act-hint").textContent = pending ? "waiting for your approval" : "";
  const send = (kinds) => fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kinds }) });
  const all = $("#approve-all"); if (all) all.onclick = () => send(acts.map((a) => a.kind));
  document.querySelectorAll(".approve-one").forEach((b) => (b.onclick = () => send([b.dataset.kind])));
  const none = $("#approve-none"); if (none) none.onclick = () => send([]);
}

init();


// ---- burst timeline strip: one lane per system, a tick per fault, voltage traces, synchronized bursts as bands ----
function renderBursts() {
  const systems = ((state.robot || {}).systems || []).map((s) => s.id);
  const evs = state.events.filter((e) => e.ts);
  if (!systems.length || evs.length < 2) { $("#bursts").innerHTML = ""; return; }
  const T = (ts) => new Date(ts.replace(" ", "T") + "Z").getTime() / 1000;
  const t0 = T(evs[0].ts), t1 = T(evs[evs.length - 1].ts) || t0 + 1, span = Math.max(t1 - t0, 1);
  const W = 420, L = 44, laneH = 16, voltH = 14, H = systems.length * laneH + voltH + 14;
  const X = (ts) => L + ((T(ts) - t0) / span) * (W - L - 4);
  const rank = { WARN: 2, WARNING: 2, ERROR: 3, FATAL: 4 };
  let h = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Fault timeline">`;
  // investigated incident spans
  for (const c of Object.values(state.candidates)) {
    const t = state.triage[c.id]; if (!t || t.decision !== "investigate") continue;
    const i = systems.indexOf(c.system); if (i < 0) continue;
    h += `<rect class="inv" x="${X(c.first_ts)}" y="${i * laneH + 1}" width="${Math.max(X(c.last_ts) - X(c.first_ts), 2)}" height="${laneH - 2}" rx="2"/>`;
  }
  // synchronized bursts: linked systems faulting within 3 s of each other (same rule as the clusterer)
  const v = state.verdict;
  if (v && v.shared_root_cause) {
    const linkedSys = new Set(v.linked_incident_ids.map((id) => (state.candidates[id] || {}).system).filter(Boolean));
    const errs = evs.filter((e) => e.level === "ERROR" && linkedSys.has(e.system));
    const seen = new Set();
    for (const e of errs) {
      const te = T(e.ts);
      if (errs.some((o) => o.system !== e.system && Math.abs(T(o.ts) - te) <= 3)) { const x = Math.round(X(e.ts)); if (!seen.has(x)) { seen.add(x); h += `<rect class="band" x="${x - 1.5}" y="0" width="3" height="${systems.length * laneH}"/>`; } }
    }
  }
  systems.forEach((id, i) => {
    const y = i * laneH;
    h += `<text x="2" y="${y + 11}">${esc(id.slice(0, 7))}</text><line class="lane" x1="${L}" y1="${y + laneH - 0.5}" x2="${W - 4}" y2="${y + laneH - 0.5}"/>`;
    for (const e of evs) if (e.system === id && (rank[e.level] || 0) >= 2) h += `<line class="tick ${esc(e.level)}" x1="${X(e.ts)}" y1="${y + (e.level === "ERROR" ? 2 : 6)}" x2="${X(e.ts)}" y2="${y + laneH - 2}"><title>${esc(e.ts.slice(11, 19))} ${esc(e.text).slice(0, 120)}</title></line>`;
  });
  // voltage traces beneath the lanes, one polyline per system that reports volts
  const vy = systems.length * laneH + 4;
  let any = false;
  systems.forEach((id, i) => {
    const pts = evs.filter((e) => e.system === id).map((e) => { const m = e.text.match(/(\d+(?:\.\d+)?)\s*V\b/); return m ? [X(e.ts), parseFloat(m[1])] : null; }).filter(Boolean);
    if (pts.length < 2) return; any = true;
    const vals = pts.map((p) => p[1]), lo = Math.min(...vals), hi = Math.max(...vals) || lo + 1;
    const path = pts.map(([x, val]) => `${x.toFixed(1)},${(vy + voltH - ((val - lo) / Math.max(hi - lo, 0.1)) * voltH).toFixed(1)}`).join(" ");
    h += `<polyline class="volt" points="${path}"><title>${esc(id)} voltage ${lo}–${hi} V</title></polyline>`;
  });
  if (any) h += `<text x="2" y="${vy + voltH}">volts</text>`;
  h += `<text x="${L}" y="${H - 2}">${esc(evs[0].ts.slice(11, 16))}</text><text x="${W - 4}" y="${H - 2}" text-anchor="end">${esc(evs[evs.length - 1].ts.slice(11, 16))}</text></svg>`;
  $("#bursts").innerHTML = h;
}

// ---- presenter autopilot: story (problem) -> run the swarm -> story again at the verdict -> stop for a human to approve ----
const autopilot = { stage: "off" };
function startAutopilot() {
  if (!["idle", "done", "error"].includes(state.status)) return;
  autopilot.stage = "intro"; $("#auto-btn").classList.add("on");
  resetUI(); state.scenario = $("#scenario").value; state.status = "idle";
  openStory();
}
function stopAutopilot() { autopilot.stage = "off"; $("#auto-btn").classList.remove("on"); }
