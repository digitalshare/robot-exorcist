const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { candidates: {}, triage: {}, steps: {}, evidence: {}, diagnoses: {}, verdict: null, actions: [], selected: null, status: "idle", logCount: 0, robot: null };
let ws = null;

async function init() {
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

async function startRun() {
  resetUI();
  const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scenario: $("#scenario").value, auto: $("#auto").checked }) });
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
  Object.assign(state, { candidates: {}, triage: {}, steps: {}, evidence: {}, diagnoses: {}, verdict: null, actions: [], selected: null, status: "idle", logCount: 0 });
  $("#logs").innerHTML = ""; $("#incidents").innerHTML = ""; $("#investigation").innerHTML = ""; $("#verdict").innerHTML = ""; $("#actions").innerHTML = ""; $("#log-count").textContent = "";
}

function setStatus(s) {
  state.status = s;
  const el = $("#status"); el.textContent = s.replace("_", " ");
  el.className = "status " + (["done", "error", "awaiting_approval", "idle"].includes(s) ? s : "running");
  if (["done", "error"].includes(s)) $("#start").disabled = false;
  if (state.actions && state.actions.length) renderActions(); // approval buttons depend on status
}

function handle(ev) {
  switch (ev.type) {
    case "reset": resetUI(); connect(); break;
    case "status": setStatus(ev.status); break;
    case "robot": state.robot = ev.robot; renderRobot(); break;
    case "log": appendLog(ev.event); break;
    case "candidates": ev.candidates.forEach((c) => (state.candidates[c.id] = c)); $("#inc-hint").textContent = `${ev.candidates.length} clusters · ${ev.embed_model}`; renderIncidents(); break;
    case "triage": ev.triage.forEach((t) => (state.triage[t.id] = t)); renderIncidents(); break;
    case "investigating": step(ev.incident_id, { kind: "start", title: ev.title }); if (!state.selected) select(ev.incident_id); break;
    case "search": step(ev.incident_id, { kind: "search", query: ev.query, results: ev.results }); break;
    case "read": step(ev.incident_id, { kind: "read", url: ev.url, title: ev.title, chars: ev.chars }); break;
    case "evidence": state.evidence[ev.incident_id] = ev.evidence; renderInvestigation(); break;
    case "diagnosis": state.diagnoses[ev.incident_id] = ev.diagnosis; renderIncidents(); renderInvestigation(); break;
    case "investigation_failed": step(ev.incident_id, { kind: "fail", error: ev.error }); break;
    case "note": step(ev.incident_id, { kind: "note", text: ev.text }); break;
    case "verdict": state.verdict = ev.verdict; renderVerdict(); break;
    case "actions": state.actions = ev.actions; renderActions(); break;
    case "error": $("#verdict").innerHTML += `<p class="err">${esc(ev.error)}\n${esc(ev.trace || "")}</p>`; break;
    case "field_agent_failed": $("#act-hint").textContent = "field agent failed, using deterministic One executor"; break;
  }
}

function renderRobot() {
  const r = state.robot || {}; const sys = (r.systems || []).map((s) => `<b>${esc(s.id)}</b> ${esc(s.kind)}`).join(" · ");
  $("#robot").innerHTML = `<b>${esc(r.cell || "")}</b> — ${sys}<br><span>${esc(r.power || "")}</span>`;
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
    const badges = [t ? `<span class="badge ${t.severity}">${t.severity}</span>` : "", t ? `<span class="badge ${t.decision}">${t.decision}</span>` : "", d ? `<span class="badge ${d.verdict}">${d.verdict}</span>` : ""].join(" ");
    return `<div class="card ${state.selected === id ? "sel" : ""}" data-id="${id}"><div class="top"><span class="title">${esc(title)}</span><span>${badges}</span></div><div class="meta">${id} · ${esc(c.system)} · ${esc(c.level)} ×${c.count} · ${esc(c.first_ts.slice(11, 19))}–${esc(c.last_ts.slice(11, 19))}${c.codes.length ? " · " + esc(c.codes.join(", ")) : ""}</div>${t ? `<div class="meta">${esc(t.why)}</div>` : ""}</div>`;
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
    if (s.kind === "start") h += `<div class="step">Investigation crew started</div>`;
    if (s.kind === "search") h += `<div class="step search">🔎 <span class="q">${esc(s.query)}</span>${s.n > 1 ? ` <span class="res">×${s.n}</span>` : ""}<div class="res">${s.results.slice(0, 4).map((r) => `<a href="${esc(r.url)}" target="_blank">${esc(r.title || r.url).slice(0, 70)}</a>`).join(" · ")}</div></div>`;
    if (s.kind === "read") h += `<div class="step read">📖 <a href="${esc(s.url)}" target="_blank">${esc(s.title || hostOf(s.url)).slice(0, 90)}</a> <span class="res">${s.chars} chars${s.n > 1 ? ` ×${s.n}` : ""}</span></div>`;
    if (s.kind === "fail") h += `<div class="step err">✖ ${esc(s.error)}</div>`;
    if (s.kind === "note") h += `<div class="step muted">ℹ ${esc(s.text)}</div>`;
  }
  if (d) {
    h += `<div class="diag"><h3><span class="badge ${d.verdict}">${d.verdict}</span> <span class="badge ${d.severity}">${d.severity}</span> ${esc(d.summary)}</h3>`;
    for (const cause of d.causes) {
      h += `<div class="cause"><div><b>${esc(cause.cause)}</b> <span class="muted">${Math.round(cause.confidence * 100)}%</span></div><div class="bar"><i style="width:${Math.round(cause.confidence * 100)}%"></i></div><div class="muted" style="font-size:12px;margin-top:4px">${esc(cause.reasoning)}</div><div class="cites">${cause.evidence_urls.map((u) => `<a href="${esc(u)}" target="_blank">${esc(hostOf(u))}</a>`).join("")}</div></div>`;
    }
    h += `<div><b>Fix tonight</b><ol class="fix">${d.fix_steps.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>`;
    if (ev && ev.evidence.length) h += `<details style="margin-top:8px"><summary class="muted">${ev.evidence.length} quotes collected</summary>${ev.evidence.map((e) => `<div class="step"><a href="${esc(e.url)}" target="_blank">${esc(e.title)}</a><div class="muted">“${esc(e.quote)}”</div></div>`).join("")}</details>`;
    h += `</div>`;
  }
  $("#investigation").innerHTML = h;
}

function hostOf(u) { try { return new URL(u).host.replace("www.", ""); } catch { return u; } }

function renderVerdict() {
  const v = state.verdict; if (!v) return;
  $("#verdict").innerHTML = `<div class="verdict"><h3>${esc(v.headline)}</h3>${v.shared_root_cause ? `<div class="rc">👻 <b>One ghost, not three:</b> ${esc(v.shared_root_cause)} <span class="muted">(${Math.round(v.confidence * 100)}% confidence)</span></div>` : `<div class="rc">No shared root cause <span class="muted">(${Math.round(v.confidence * 100)}%)</span></div>`}<p>${esc(v.narrative)}</p><p class="muted">linked: ${v.linked_incident_ids.join(", ") || "—"} · false alarms: ${v.false_alarm_ids.join(", ") || "—"}</p><b>Recommended fix</b><ol class="fix">${v.recommended_fix.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>`;
}

function renderActions() {
  const acts = state.actions || [];
  const pending = acts.some((a) => a.status === "proposed") && state.status === "awaiting_approval";
  let h = pending ? `<div class="approve"><button id="approve-all">Approve all</button>${acts.map((a) => `<button class="ghost approve-one" data-kind="${a.kind}">Only ${a.kind.replace("_", " ")}</button>`).join("")}<button class="ghost" id="approve-none">Skip</button></div>` : "";
  h += acts.map((a) => `<div class="action"><div class="top"><b>${a.kind === "slack_alert" ? "💬 Slack alert" : "🐙 GitHub issue"} <span class="muted">${esc(a.title)}</span></b><span class="st ${a.status}">${a.status}${a.result_url ? ` · <a href="${esc(a.result_url)}" target="_blank">open</a>` : ""}</span></div>${a.result_note ? `<div class="muted" style="font-size:11px">${esc(a.result_note)}</div>` : ""}<pre>${esc(a.body)}</pre></div>`).join("");
  $("#actions").innerHTML = h;
  $("#act-hint").textContent = pending ? "waiting for your approval" : "";
  const send = (kinds) => fetch("/api/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kinds }) });
  const all = $("#approve-all"); if (all) all.onclick = () => send(acts.map((a) => a.kind));
  document.querySelectorAll(".approve-one").forEach((b) => (b.onclick = () => send([b.dataset.kind])));
  const none = $("#approve-none"); if (none) none.onclick = () => send([]);
}

init();
