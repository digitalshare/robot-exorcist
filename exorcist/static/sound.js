// Synthesized sound cues (Web Audio, no files). Off by default; the toggle creates the AudioContext on a user gesture.
(function () {
  let ctx = null, enabled = false;
  try { enabled = localStorage.getItem("exorcist.sound") === "1"; } catch {}
  const now = () => ctx.currentTime;
  function ensure() { if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)(); if (ctx.state === "suspended") ctx.resume(); return ctx; }
  function tone({ type = "sine", freq = 440, at = 0, dur = 0.3, gain = 0.2, slide = null }) {
    if (!enabled || !ctx) return;
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, now() + at);
    if (slide) o.frequency.exponentialRampToValueAtTime(slide, now() + at + dur);
    g.gain.setValueAtTime(0.0001, now() + at); g.gain.exponentialRampToValueAtTime(gain, now() + at + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, now() + at + dur);
    o.connect(g).connect(ctx.destination); o.start(now() + at); o.stop(now() + at + dur + 0.05);
  }
  let lastHum = 0;
  const api = {
    get enabled() { return enabled; },
    toggle() { enabled = !enabled; try { localStorage.setItem("exorcist.sound", enabled ? "1" : "0"); } catch {} if (enabled) { ensure(); api.chime(); } return enabled; },
    hum() { if (!enabled || !ctx) return; const t = performance.now(); if (t - lastHum < 1500) return; lastHum = t; tone({ type: "sawtooth", freq: 55, dur: 1.3, gain: 0.12, slide: 40 }); tone({ type: "sine", freq: 110, dur: 1.3, gain: 0.05, slide: 70 }); },
    thunk() { tone({ type: "sine", freq: 95, dur: 0.18, gain: 0.3, slide: 40 }); tone({ type: "square", freq: 60, dur: 0.06, gain: 0.08 }); },
    chime() { tone({ freq: 880, dur: 0.25, gain: 0.12 }); tone({ freq: 1320, at: 0.12, dur: 0.35, gain: 0.1 }); },
    gong() { tone({ freq: 196, dur: 1.8, gain: 0.18 }); tone({ freq: 294, dur: 1.4, gain: 0.08 }); tone({ type: "triangle", freq: 98, dur: 2.2, gain: 0.1 }); },
    sparkle() { [523, 659, 784, 1047, 1319].forEach((f, i) => tone({ freq: f, at: i * 0.09, dur: 0.4, gain: 0.1 })); },
  };
  if (enabled) document.addEventListener("pointerdown", () => ensure(), { once: true });
  window.exorcistSound = api;
})();
