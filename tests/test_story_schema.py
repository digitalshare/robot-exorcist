import re
from pathlib import Path

import yaml

from exorcist.logs import load_scenario

EFFECTS = {"warn", "freeze", "disconnect", "voltage", "tremble", "stop_spin", "halt", "flicker", "benign", "recover", "plan", "collide", "refuse", "overrange"}


def _matches(cue, ev):
    if cue.get("system") and ev.system != cue["system"]:
        return False
    m = str(cue["match"])
    if m.startswith("/") and m.rfind("/") > 0:
        return re.search(m[1 : m.rfind("/")], ev.text) is not None
    return m in ev.text


def test_every_scenario_story_is_consistent_with_its_logs():
    for folder in sorted(Path("samples").iterdir()):
        if not (folder / "robot.yaml").exists():
            continue
        robot, events = load_scenario(folder)
        story = robot.get("story")
        assert story and story.get("cues"), f"{folder} has no story block"
        systems = {s["id"] for s in robot["systems"]}
        for cue in story["cues"]:
            assert cue["effect"] in EFFECTS, (folder, cue)
            assert not cue.get("system") or cue["system"] in systems, (folder, cue)
            assert any(_matches(cue, e) for e in events), f"{folder}: cue {cue['match']!r} matches no log line"
        for key in ("verdict_shared", "verdict_separate"):
            assert story.get("chapters", {}).get(key), (folder, key)


def test_vendored_three_is_present():
    v = Path("exorcist/static/vendor")
    assert (v / "three.module.min.js").stat().st_size > 100_000
    assert "three.module.min.js" in (v / "OrbitControls.js").read_text()
