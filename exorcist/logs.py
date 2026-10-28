"""Log parsing and normalisation. Deterministic; no model calls."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml

LINE_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*"
    r"\[(?P<level>[A-Z]+)\]\s*"
    r"\[(?P<source>[^\]]+)\]:?\s*(?P<text>.*)$"
)
# ROS 2 console format: [LEVEL] [unix_ts] [node]: text
ROS_RE = re.compile(r"^\[(?P<level>[A-Z]+)\]\s*\[(?P<ts>\d+(?:\.\d+)?)\]\s*\[(?P<source>[^\]]+)\]:?\s*(?P<text>.*)$")
CODE_RE = re.compile(r"\b(C\d{2,3}A\d+|0x[0-9A-Fa-f]{2,}|[A-Z][A-Z_]{4,}(?:_[A-Z]+)*)\b")

LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARN": 2, "WARNING": 2, "ERROR": 3, "FATAL": 4}


@dataclass
class LogEvent:
    ts: str
    level: str
    source: str
    text: str
    system: str
    code: str | None = None
    raw: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rank(self) -> int:
        return LEVEL_RANK.get(self.level.upper(), 1)


def parse_line(line: str, system: str) -> LogEvent | None:
    line = line.rstrip("\n")
    if not line.strip():
        return None
    m = LINE_RE.match(line) or ROS_RE.match(line)
    if not m:
        return LogEvent(ts="", level="INFO", source=system, text=line.strip(), system=system, raw=line)
    ts = m.group("ts")
    if ts.replace(".", "", 1).isdigit():
        ts = datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    text = m.group("text").strip()
    code = None
    cm = CODE_RE.search(text)
    if cm:
        cand = cm.group(1)
        # ignore shouty words that are not codes
        if not cand.isupper() or "_" in cand or cand.startswith(("C", "0x")):
            code = cand
    return LogEvent(ts=ts, level=m.group("level").upper(), source=m.group("source"), text=text, system=system, code=code, raw=line)


def parse_text(text: str, system: str) -> list[LogEvent]:
    return [e for e in (parse_line(l, system) for l in text.splitlines()) if e]


def load_scenario(path: str | Path) -> tuple[dict, list[LogEvent]]:
    """Load robot.yaml and every log it references (or every *.log in the folder)."""
    path = Path(path)
    robot: dict = {}
    yaml_path = path / "robot.yaml"
    if yaml_path.exists():
        robot = yaml.safe_load(yaml_path.read_text()) or {}
    events: list[LogEvent] = []
    systems = robot.get("systems") or []
    if systems:
        for s in systems:
            lp = path / s["log"]
            if lp.exists():
                events.extend(parse_text(lp.read_text(), s["id"]))
    else:
        for lp in sorted(path.glob("*.log")):
            events.extend(parse_text(lp.read_text(), lp.stem))
    events.sort(key=lambda e: e.ts)
    return robot, events


NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
HEX_RE = re.compile(r"0x[0-9A-Fa-f]+")
PATH_RE = re.compile(r"/[\w./-]+")
WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Strip volatile tokens so repeated occurrences of one fault share a signature."""
    t = HEX_RE.sub("<hex>", text)
    t = PATH_RE.sub("<path>", t)
    t = NUM_RE.sub("<n>", t)
    t = WS_RE.sub(" ", t).strip()
    return t


def signature(e: LogEvent) -> str:
    return f"{e.system}|{e.level}|{e.source}|{normalize(e.text)}"


def interesting(events: Iterable[LogEvent]) -> list[LogEvent]:
    """Events worth clustering: WARN and above."""
    return [e for e in events if e.rank >= 2]
