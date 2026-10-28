// 3D story mode: a stylized, data-driven model of the robot cell that replays the scenario's log with
// plain-language captions, then shows what the swarm found. Everything here is generic; the narrative
// comes from the `story` block in each scenario's robot.yaml.
import * as THREE from "./vendor/three.module.min.js";
import { OrbitControls } from "./vendor/OrbitControls.js";

const C = { bg: 0x0a0c12, bench: 0x161a24, metal: 0x9aa3b8, dark: 0x2a3040, accent: 0xff7a1a, red: 0xff5d5d, amber: 0xffcc4d, green: 0x5ad77a, blue: 0x4fa3ff, violet: 0x9b7bff };
const SPEEDS = [10, 30, 100];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function kindOf(kind = "", id = "") {
  const k = (kind + " " + id).toLowerCase();
  if (/arm|ur5|ur3|ur10|manipulator|cobot|franka|kuka/.test(k)) return "arm";
  if (/grip|hand|dynamixel|servo/.test(k)) return "gripper";
  if (/amr|rover|turtlebot|nav2|mobile|agv|base/.test(k)) return "rover";
  return "generic";
}
function mat(color, extra = {}) { return new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.25, ...extra }); }
function box(w, h, d, m) { return new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); }
function cyl(rt, rb, h, m, seg = 24) { return new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m); }
function sph(r, m) { return new THREE.Mesh(new THREE.SphereGeometry(r, 20, 16), m); }
function tsSeconds(ts) { const d = new Date(String(ts).replace(" ", "T") + (String(ts).endsWith("Z") ? "" : "Z")); return isNaN(d) ? null : d.getTime() / 1000; }

// ------------------------------------------------------------------ rigs
// Every rig returns { group, anchor (label point), tints: [meshes that take a colour], idle(t, s), parts }
function makeArm(withCamera) {
  const g = new THREE.Group();
  const body = mat(C.metal), joint = mat(0x5b6480), tints = [];
  const base = cyl(0.28, 0.32, 0.16, mat(C.dark)); base.position.y = 0.08; g.add(base);
  const shoulder = new THREE.Group(); shoulder.position.y = 0.16; g.add(shoulder);
  const j0 = sph(0.16, joint.clone()); shoulder.add(j0); tints.push(j0);
  const upper = new THREE.Group(); upper.position.y = 0.0; shoulder.add(upper);
  const upperArm = box(0.16, 0.95, 0.16, body.clone()); upperArm.position.y = 0.48; upper.add(upperArm); tints.push(upperArm);
  const elbow = new THREE.Group(); elbow.position.y = 0.95; upper.add(elbow);
  const j1 = sph(0.14, joint.clone()); elbow.add(j1); tints.push(j1);
  const fore = box(0.13, 0.8, 0.13, body.clone()); fore.position.y = 0.4; elbow.add(fore); tints.push(fore);
  const wrist = new THREE.Group(); wrist.position.y = 0.8; elbow.add(wrist);
  const j2 = sph(0.11, joint.clone()); wrist.add(j2); tints.push(j2);
  const tool = cyl(0.05, 0.07, 0.22, mat(C.dark)); tool.position.y = 0.16; wrist.add(tool);
  let cam = null;
  if (withCamera) { cam = box(0.16, 0.12, 0.2, mat(0x3a4157)); cam.position.set(0.18, 0.02, 0); wrist.add(cam); tints.push(cam); }
  const anchor = new THREE.Object3D(); anchor.position.set(0, 0.25, 0); elbow.add(anchor);
  const parts = { shoulder, upper, elbow, wrist, j2, cam, tool };
  return {
    group: g, anchor, tints, parts,
    idle(t, s) {
      if (s.frozen || s.collided) return;
      shoulder.rotation.y = Math.sin(t * 0.5) * 0.9;
      upper.rotation.z = -0.35 + Math.sin(t * 0.7) * 0.25;
      elbow.rotation.z = 0.9 + Math.sin(t * 0.7 + 1) * 0.35;
      wrist.rotation.z = -0.4 + Math.sin(t * 1.1) * 0.3;
    },
  };
}
function makeGripper(mountOn) {
  const g = new THREE.Group();
  const tints = [];
  const palm = box(0.3, 0.1, 0.2, mat(C.violet)); tints.push(palm);
  const f1 = box(0.05, 0.26, 0.14, mat(0xc9cedb)), f2 = f1.clone(); f1.position.set(-0.09, -0.16, 0); f2.position.set(0.09, -0.16, 0); tints.push(f1, f2);
  g.add(palm, f1, f2);
  const anchor = new THREE.Object3D(); anchor.position.set(0, -0.45, 0); g.add(anchor);
  if (mountOn) { g.position.y = 0.32; g.rotation.z = Math.PI; mountOn.add(g); }
  else { const ped = cyl(0.12, 0.16, 0.6, mat(C.dark)); ped.position.y = 0.3; const holder = new THREE.Group(); holder.add(ped); g.position.y = 0.75; g.rotation.z = Math.PI; holder.add(g); return wrap(holder); }
  return wrap(g);
  function wrap(root) {
    return {
      group: root, anchor, tints, parts: { f1, f2 },
      idle(t, s) {
        const jitter = s.trembling ? (Math.random() - 0.5) * 0.05 : 0;
        const open = s.frozen ? 0.12 : 0.08 + Math.abs(Math.sin(t * 0.7)) * 0.1;
        f1.position.x = -open + jitter; f2.position.x = open - jitter;
      },
    };
  }
}
function makeRover() {
  const g = new THREE.Group();
  const tints = [];
  const body = cyl(0.36, 0.36, 0.18, mat(C.metal)); body.position.y = 0.14; g.add(body); tints.push(body);
  const deck = cyl(0.3, 0.3, 0.06, mat(C.dark)); deck.position.y = 0.26; g.add(deck);
  const lidar = cyl(0.09, 0.09, 0.08, mat(0x5b6480)); lidar.position.y = 0.33; g.add(lidar); tints.push(lidar);
  const eye = box(0.03, 0.03, 0.1, mat(C.red, { emissive: C.red, emissiveIntensity: 0.8 })); eye.position.set(0, 0, 0.06); lidar.add(eye);
  for (const sx of [-1, 1]) { const w = cyl(0.1, 0.1, 0.05, mat(0x111318)); w.rotation.z = Math.PI / 2; w.position.set(sx * 0.37, 0.1, 0); g.add(w); }
  const anchor = new THREE.Object3D(); anchor.position.y = 0.5; g.add(anchor);
  const home = new THREE.Vector3();
  return {
    group: g, anchor, tints, parts: { lidar },
    setHome(p) { home.copy(p); },
    idle(t, s) {
      if (!s.spinStopped) lidar.rotation.y += 0.25;
      if (s.halted || s.frozen) return;
      const a = t * 0.6;
      g.position.set(home.x + Math.cos(a) * 0.55, home.y, home.z + Math.sin(a) * 0.45);
      g.rotation.y = -a + Math.PI / 2;
    },
  };
}
function makeGeneric() {
  const g = new THREE.Group(); const tints = [];
  const b = box(0.5, 0.5, 0.5, mat(C.metal)); b.position.y = 0.25; g.add(b); tints.push(b);
  for (const sx of [-1, 1]) { const e = sph(0.05, mat(0x111318)); e.position.set(sx * 0.12, 0.33, 0.26); g.add(e); }
  const anchor = new THREE.Object3D(); anchor.position.y = 0.7; g.add(anchor);
  return { group: g, anchor, tints, parts: {}, idle(t, s) { if (!s.frozen) g.rotation.y = Math.sin(t * 0.4) * 0.3; } };
}
function makeGhost() {
  const g = new THREE.Group();
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, roughness: 0.9 });
  const head = sph(0.16, m); g.add(head);
  const skirt = cyl(0.16, 0.19, 0.22, m); skirt.position.y = -0.11; g.add(skirt);
  for (const sx of [-1, 1]) { const e = sph(0.03, mat(0x111318)); e.position.set(sx * 0.06, 0.03, 0.14); g.add(e); }
  g.visible = false;
  return g;
}

// ------------------------------------------------------------------ story
export function createStory(container) {
  container.classList.add("story-root");
  container.innerHTML = `
    <div class="story-stage"></div>
    <div class="story-labels"></div>
    <div class="story-caption"><div class="story-title"></div><div class="story-text"></div></div>
    <div class="story-chips"></div>
    <div class="story-bar">
      <button class="s-play">▶</button>
      <select class="s-speed">${SPEEDS.map((s) => `<option value="${s}">${s}×</option>`).join("")}</select>
      <input class="s-scrub" type="range" min="0" max="1000" value="0">
      <span class="s-time">--:--:--</span>
      <span class="s-ticker"></span>
    </div>`;
  const stage = container.querySelector(".story-stage"), labelsEl = container.querySelector(".story-labels");
  const capTitle = container.querySelector(".story-title"), capText = container.querySelector(".story-text");
  const chipsEl = container.querySelector(".story-chips"), playBtn = container.querySelector(".s-play"), speedSel = container.querySelector(".s-speed");
  const scrub = container.querySelector(".s-scrub"), timeEl = container.querySelector(".s-time"), ticker = container.querySelector(".s-ticker");

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(C.bg);
  stage.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(C.bg, 9, 16);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 60);
  camera.position.set(2.2, 3.1, 5.8);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0.4, 0.9, 0); controls.enableDamping = true; controls.maxPolarAngle = Math.PI / 2.05; controls.minDistance = 3; controls.maxDistance = 14;
  scene.add(new THREE.HemisphereLight(0xcfd6ff, 0x1a1420, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1); sun.position.set(4, 7, 5); scene.add(sun);
  const fill = new THREE.PointLight(C.accent, 0.0, 8); fill.position.set(-3.1, 1.2, 0); scene.add(fill);

  // bench + PSU
  const bench = box(9, 0.12, 4.2, mat(C.bench, { roughness: 0.9 })); bench.position.y = -0.06; scene.add(bench);
  const grid = new THREE.GridHelper(9, 18, 0x232838, 0x1b202c); grid.position.y = 0.001; scene.add(grid);
  const psu = new THREE.Group(); psu.position.set(-3.2, 0, 0.2); scene.add(psu);
  const psuBox = box(0.8, 0.5, 0.6, mat(0x3a2a44)); psuBox.position.y = 0.25; psu.add(psuBox);
  const plate = box(0.6, 0.3, 0.02, mat(0x1b1420)); plate.position.set(0, 0.25, 0.31); psu.add(plate);
  for (let i = 0; i < 3; i++) { const slot = box(0.4, 0.03, 0.01, mat(0x5b6480)); slot.position.set(0, 0.17 + i * 0.08, 0.325); psu.add(slot); }
  const lampMat = new THREE.MeshStandardMaterial({ color: C.accent, emissive: C.accent, emissiveIntensity: 1.2 });
  const lamp = sph(0.07, lampMat); lamp.position.set(0.25, 0.55, 0.2); psu.add(lamp);
  const psuAnchor = new THREE.Object3D(); psuAnchor.position.y = 0.85; psu.add(psuAnchor);
  const ghostPSU = makeGhost(); ghostPSU.position.set(0.55, 0.9, 0.3); psu.add(ghostPSU);

  const rigs = {}; // system id -> {rig, state, label, cable, ghost}
  const labels = []; // {el, anchor}
  let story = { cues: [], chapters: {} }, robot = {}, events = [], cueHits = [], tints = {};
  let shared = false;

  function addLabel(anchor, html, cls = "") { const el = document.createElement("div"); el.className = "story-label " + cls; el.innerHTML = html; labelsEl.appendChild(el); const L = { el, anchor }; labels.push(L); return L; }

  function clearScene() {
    for (const id of Object.keys(rigs)) { scene.remove(rigs[id].rig.group); if (rigs[id].cable) scene.remove(rigs[id].cable); }
    for (const id in rigs) delete rigs[id];
    labels.splice(0).forEach((l) => l.el.remove());
    chipsEl.innerHTML = ""; ghostPSU.visible = false; shared = false; fill.intensity = 0;
  }

  function load(data) {
    clearScene();
    robot = data.robot || {}; events = (data.events || []).filter((e) => e.ts).slice(); story = robot.story || { cues: [], chapters: {} };
    events.sort((a, b) => (a.ts < b.ts ? -1 : 1));
    const systems = robot.systems || [];
    const needsCamera = (story.cues || []).some((c) => c.effect === "collide");
    const kinds = systems.map((s) => kindOf(s.kind, s.id));
    const arm = systems[kinds.indexOf("arm")];
    const n = systems.filter((s, i) => !(kinds[i] === "gripper" && arm)).length;
    let slot = 0;
    systems.forEach((sys, i) => {
      const kind = kinds[i];
      let rig, pos;
      if (kind === "gripper" && arm && rigs[arm.id]) { rig = makeGripper(rigs[arm.id].rig.parts.wrist); }
      else {
        pos = new THREE.Vector3(-1.4 + (n > 1 ? slot * (4.2 / (n - 1)) : 1.0), 0, kind === "rover" ? 1.1 : -0.3); slot++;
        rig = kind === "arm" ? makeArm(needsCamera) : kind === "gripper" ? makeGripper(null) : kind === "rover" ? makeRover() : makeGeneric();
        rig.group.position.copy(pos); if (rig.setHome) rig.setHome(pos); scene.add(rig.group);
      }
      const state = {};
      const label = addLabel(rig.anchor, `<b>${esc(sys.id)}</b><span>${esc(String(sys.kind || "").split("(")[0].trim())}</span><em></em>`);
      let cable = null;
      if (pos) {
        const pts = [new THREE.Vector3(-2.8, 0.05, 0.2), new THREE.Vector3((pos.x - 2.8) / 2, 0.05, (pos.z + 0.2) / 2), new THREE.Vector3(pos.x, 0.05, pos.z)];
        const geo = new THREE.BufferGeometry().setFromPoints(new THREE.CatmullRomCurve3(pts).getPoints(30));
        cable = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: 0x3a4157, dashSize: 0.12, gapSize: 0.08, transparent: true, opacity: 0.9 }));
        cable.computeLineDistances(); scene.add(cable);
      }
      const ghost = makeGhost(); ghost.position.set(0, 1.3, 0); rig.group.add(ghost);
      rigs[sys.id] = { rig, state, label, cable, ghost, kind };
      tints[sys.id] = rig.tints.map((m) => ({ m, base: m.material.color.getHex() }));
    });
    addLabel(psuAnchor, `<b>shared power</b><span>${esc(String(robot.power || "bench supply").split(".")[0].slice(0, 60))}</span><em></em>`);
    capTitle.textContent = story.title || robot.cell || "Robot cell";
    capText.textContent = story.intro || robot.power || "";
    cueHits = (story.cues || []).map(() => 0);
    t0 = events.length ? tsSeconds(events[0].ts) : 0; tEnd = events.length ? tsSeconds(events[events.length - 1].ts) : 1;
    cursor = 0; vt = t0; playing = false; playBtn.textContent = "▶";
    resize();
  }

  // ------------------------------------------------------------ effects
  const timers = []; // {until, undo}
  function later(sec, undo) { timers.push({ until: performance.now() + sec * 1000, undo }); }
  function tint(id, color, sec) {
    const list = tints[id]; if (!list) return;
    list.forEach(({ m }) => m.material.color.setHex(color));
    if (sec) later(sec, () => list.forEach(({ m, base }) => m.material.color.setHex(base)));
  }
  function badge(id, text, cls, sec) { const r = rigs[id]; if (!r) return; const em = r.label.el.querySelector("em"); em.textContent = text; em.className = cls; if (sec) later(sec, () => { if (em.textContent === text) { em.textContent = ""; em.className = ""; } }); }
  function flickerPSU(sec = 2.2) {
    const start = performance.now();
    const step = () => { const k = (performance.now() - start) / 1000; if (k > sec) { lampMat.emissiveIntensity = 1.2; fill.intensity = shared ? 1.2 : 0; return; } lampMat.emissiveIntensity = Math.random() < 0.5 ? 0.15 : 1.4; fill.intensity = lampMat.emissiveIntensity; requestAnimationFrame(step); };
    step();
    for (const id in rigs) { const c = rigs[id].cable; if (c) { c.material.color.setHex(C.accent); later(sec, () => c.material.color.setHex(shared ? C.accent : 0x3a4157)); } }
  }
  const EFFECTS = {
    warn: (id) => { tint(id, C.amber, 3); badge(id, "slowing down", "warn", 3); },
    freeze: (id) => { const s = rigs[id]?.state; if (!s) return; s.frozen = true; tint(id, C.red, 3.5); badge(id, "protective stop", "err", 3.5); later(3.5, () => (s.frozen = false)); },
    disconnect: (id) => badge(id, "no signal", "err", 2.5),
    voltage: (id, value) => badge(id, value ? `${value} V` : "low voltage", "warn", 3.5),
    tremble: (id) => { const s = rigs[id]?.state; if (!s) return; s.trembling = true; tint(id, C.red, 3); badge(id, "overload, motor off", "err", 3); later(3, () => (s.trembling = false)); },
    stop_spin: (id) => { const s = rigs[id]?.state; if (!s) return; s.spinStopped = true; tint(id, C.red, 3.5); badge(id, "laser silent", "err", 3.5); later(3.5, () => (s.spinStopped = false)); },
    halt: (id) => { const s = rigs[id]?.state; if (!s) return; s.halted = true; badge(id, "stuck", "err", 3); later(3, () => (s.halted = false)); },
    flicker: () => flickerPSU(),
    benign: (id) => badge(id, "harmless chatter", "muted", 3),
    recover: (id) => { const r = rigs[id]; if (!r) return; Object.assign(r.state, { frozen: false, trembling: false, spinStopped: false, halted: false }); (tints[id] || []).forEach(({ m, base }) => m.material.color.setHex(base)); },
    plan: (id) => { tint(id, C.blue, 2); badge(id, "planning a move", "info", 2); },
    collide: (id) => { const r = rigs[id]; if (!r) return; const p = r.rig.parts; r.state.collided = true; if (p.wrist) { p.shoulder.rotation.y = 0.4; p.upper.rotation.z = -0.5; p.elbow.rotation.z = 1.5; p.wrist.rotation.z = 1.25; } [p.j2, p.cam].forEach((m) => m && m.material.color.setHex(C.red)); badge(id, "wrist touches camera mount", "err", 4); },
    refuse: (id) => badge(id, "move refused", "err", 3),
    overrange: (id, value) => { const r = rigs[id]; if (!r) return; const p = r.rig.parts; if (p.j2) p.j2.material.color.setHex(C.amber); badge(id, value ? `wrist at ${value} rad` : "joint out of range", "warn", 4); },
  };
  let holdUntil = 0; // after a visible effect the clock runs at 1x for a moment so the audience can see it
  function fire(cue, ev) {
    const target = cue.system || Object.keys(rigs)[0];
    if (!["recover", "flicker"].includes(cue.effect)) holdUntil = Math.max(holdUntil, performance.now() + 2200);
    const num = (ev.text.match(/(\d+(?:\.\d+)?)\s*(?:V\b|rad\b)/) || ev.text.match(/(\d+(?:\.\d+)?)/) || [])[1];
    (EFFECTS[cue.effect] || (() => {}))(target, num);
    return num;
  }
  function matches(cue, ev) {
    if (cue.system && ev.system !== cue.system) return false;
    const m = String(cue.match || "");
    if (m.startsWith("/") && m.lastIndexOf("/") > 0) { try { return new RegExp(m.slice(1, m.lastIndexOf("/")), m.slice(m.lastIndexOf("/") + 1)).test(ev.text); } catch { return false; } }
    return ev.text.includes(m);
  }
  function caption(text) { capText.classList.remove("fade"); void capText.offsetWidth; capText.textContent = text; capText.classList.add("fade"); }
  function handle(ev) {
    ticker.textContent = `${ev.ts.slice(11, 19)} ${ev.system}/${ev.source}: ${ev.text}`.slice(0, 140);
    (story.cues || []).forEach((cue, i) => {
      if (!matches(cue, ev)) return;
      cueHits[i]++;
      const num = fire(cue, ev);
      const after = cue.after || 0;
      if (cue.caption && ((cue.once && cueHits[i] === 1) || (!cue.once && cueHits[i] > after))) caption(cue.caption.replace("{value}", num || ""));
    });
  }

  // ------------------------------------------------------------ run events (chapters)
  function applyRunEvent(ev) {
    if (ev.type === "diagnosis") {
      const r = rigs[ev.system]; if (!r) return;
      const d = ev.diagnosis; const cites = new Set(d.causes.flatMap((c) => c.evidence_urls)).size;
      addLabel(r.rig.anchor, `<i class="${d.verdict}">${esc(d.verdict)}</i> ${esc(d.summary).slice(0, 140)}${d.summary.length > 140 ? "…" : ""}<small>${cites} cited source${cites === 1 ? "" : "s"}</small>`, "callout");
      if (story.chapters && story.chapters.investigation && !chapterShown.investigation) { chapterShown.investigation = true; caption(story.chapters.investigation); }
    } else if (ev.type === "verdict") {
      const v = ev.verdict; shared = !!v.shared_root_cause;
      if (shared) {
        ghostPSU.visible = true; fill.intensity = 1.2;
        for (const id in rigs) { const c = rigs[id].cable; if (c) { c.material.color.setHex(C.accent); c.material.opacity = 1; } }
        caption((story.chapters && story.chapters.verdict_shared) || v.headline);
      } else {
        for (const id in rigs) rigs[id].ghost.visible = true;
        caption((story.chapters && story.chapters.verdict_separate) || v.headline);
      }
      capTitle.textContent = v.headline;
    } else if (ev.type === "actions") {
      const done = ev.actions.filter((a) => a.status === "done");
      chipsEl.innerHTML = ev.actions.map((a) => `<span class="chip ${a.status}">${a.kind === "slack_alert" ? "Slack alert" : "GitHub issue"}: ${esc(a.status)}${a.result_url ? ` · <a href="${esc(a.result_url)}" target="_blank">open</a>` : ""}</span>`).join("");
      if (done.length && story.chapters && story.chapters.actions && !chapterShown.actions) { chapterShown.actions = true; caption(story.chapters.actions); }
    }
  }
  const chapterShown = {};

  // ------------------------------------------------------------ clock + loop
  let t0 = 0, tEnd = 1, vt = 0, cursor = 0, playing = false, speed = SPEEDS[1], last = performance.now(), disposed = false;
  speedSel.value = String(speed);
  speedSel.onchange = () => (speed = Number(speedSel.value));
  playBtn.onclick = () => { if (!playing && vt >= tEnd) seek(0); playing = !playing; playBtn.textContent = playing ? "❚❚" : "▶"; };
  scrub.oninput = () => seek(Number(scrub.value) / 1000);
  function seek(frac) {
    vt = t0 + (tEnd - t0) * frac; cursor = 0; cueHits = cueHits.map(() => 0);
    while (cursor < events.length && tsSeconds(events[cursor].ts) < vt) cursor++;
    for (const id in rigs) EFFECTS.recover(id);
  }
  function fmt(sec) { const d = new Date(sec * 1000); return d.toISOString().slice(11, 19); }
  function resize() { const w = stage.clientWidth || 800, h = stage.clientHeight || 450; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  const ro = new ResizeObserver(resize); ro.observe(stage);
  const v3 = new THREE.Vector3();
  function frame(now) {
    if (disposed) return;
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.1); last = now;
    if (playing) {
      vt += dt * (now < holdUntil ? 1 : speed);
      while (cursor < events.length && tsSeconds(events[cursor].ts) <= vt) handle(events[cursor++]);
      if (vt >= tEnd) { vt = tEnd; playing = false; playBtn.textContent = "↺"; }
      scrub.value = String(Math.round(((vt - t0) / Math.max(tEnd - t0, 1)) * 1000));
    }
    timeEl.textContent = events.length ? fmt(vt) : "--:--:--";
    for (let i = timers.length - 1; i >= 0; i--) if (now >= timers[i].until) { timers[i].undo(); timers.splice(i, 1); }
    const t = now / 1000;
    for (const id in rigs) rigs[id].rig.idle(t, rigs[id].state);
    ghostPSU.position.y = 0.9 + Math.sin(t * 2) * 0.06;
    for (const id in rigs) { const g = rigs[id].ghost; g.position.y = 1.3 + Math.sin(t * 2 + id.length) * 0.06; g.rotation.y = t; }
    controls.update();
    renderer.render(scene, camera);
    const w = stage.clientWidth, h = stage.clientHeight;
    for (const L of labels) { L.anchor.getWorldPosition(v3).project(camera); L.el.style.transform = `translate(-50%,-100%) translate(${(v3.x * 0.5 + 0.5) * w}px,${(-v3.y * 0.5 + 0.5) * h}px)`; L.el.style.opacity = v3.z < 1 ? "1" : "0"; }
  }
  requestAnimationFrame(frame);

  return {
    load, applyRunEvent, seek,
    play() { playing = true; playBtn.textContent = "❚❚"; },
    pause() { playing = false; playBtn.textContent = "▶"; },
    dispose() { disposed = true; ro.disconnect(); controls.dispose(); renderer.dispose(); container.innerHTML = ""; container.classList.remove("story-root"); },
  };
}
