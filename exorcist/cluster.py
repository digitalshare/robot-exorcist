"""Turn WARN+ log events into incident candidates: embed unique signatures (Parasail), agglomerate by cosine."""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

import numpy as np

from .logs import LogEvent, normalize, signature, interesting
from .schemas import IncidentCandidate

Embedder = Callable[[list[str]], list[list[float]]]


def _agglomerate_affinity(aff: np.ndarray, threshold: float) -> list[int]:
    """Average-linkage agglomerative clustering on a pairwise affinity matrix. Small n, so O(n^3) is fine."""
    n = len(aff)
    if n == 0:
        return []
    clusters: list[list[int]] = [[i] for i in range(n)]
    while len(clusters) > 1:
        best, bi, bj = -1.0, -1, -1
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                s = float(aff[np.ix_(clusters[i], clusters[j])].mean())
                if s > best:
                    best, bi, bj = s, i, j
        if best < threshold:
            break
        clusters[bi].extend(clusters.pop(bj))
    labels = [0] * n
    for k, c in enumerate(clusters):
        for i in c:
            labels[i] = k
    return labels


def _ts_seconds(ts: str) -> float | None:
    try:
        from datetime import datetime

        return datetime.fromisoformat(ts.replace(" ", "T")).timestamp()
    except Exception:
        return None


def _cooccurrence(a: list[float], b: list[float], window: float) -> float:
    """Highest of: share of A occurrences with a B within `window` s, and vice versa (a rare warning that always fires inside a burst joins it)."""
    if not a or not b:
        return 0.0

    def rate(x, y):
        y = sorted(y)
        hits = 0
        for t in x:
            lo = np.searchsorted(y, t - window)
            if lo < len(y) and abs(y[lo] - t) <= window:
                hits += 1
            elif lo > 0 and abs(y[lo - 1] - t) <= window:
                hits += 1
        return hits / len(x)

    return max(rate(a, b), rate(b, a))


def build_candidates(events: list[LogEvent], embedder: Embedder, *, threshold: float = 0.78, window: float = 3.0, cooccur: float = 0.75, per_system: bool = True) -> list[IncidentCandidate]:
    """Two signatures belong to one incident if they mean the same thing (embedding cosine >= threshold)
    or if they keep happening together (>= `cooccur` of their occurrences within `window` seconds)."""
    warn_plus = interesting(events)
    if not warn_plus:
        return []
    # one embedding per unique signature, not per line
    by_sig: dict[str, list[LogEvent]] = defaultdict(list)
    for e in warn_plus:
        by_sig[signature(e)].append(e)
    sigs = list(by_sig.keys())
    texts = [f"[{by_sig[s][0].system}] [{by_sig[s][0].source}] {normalize(by_sig[s][0].text)}" for s in sigs]
    vecs = np.array(embedder(texts), dtype=float)
    unit = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    cos = unit @ unit.T
    times = [[t for t in (_ts_seconds(e.ts) for e in by_sig[s]) if t is not None] for s in sigs]

    # cluster within each system (a UR fault and an AMR fault are different incidents even if the words rhyme)
    groups: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sigs):
        groups[by_sig[s][0].system if per_system else "all"].append(i)

    candidates: list[IncidentCandidate] = []
    n = 0
    for system, idxs in groups.items():
        sub = np.zeros((len(idxs), len(idxs)))
        for a, i in enumerate(idxs):
            for b, j in enumerate(idxs):
                if a == b:
                    sub[a, b] = 1.0
                    continue
                sem = cos[i, j] / threshold  # 1.0 at the semantic threshold
                tmp = 1.0 if _cooccurrence(times[i], times[j], window) >= cooccur else 0.0
                sub[a, b] = max(min(sem, 1.0) if sem >= 1.0 else cos[i, j], tmp)
        labels = _agglomerate_affinity(sub, threshold)
        members: dict[int, list[int]] = defaultdict(list)
        for local, lab in enumerate(labels):
            members[lab].append(idxs[local])
        for lab, sig_idx in members.items():
            evs = [e for i in sig_idx for e in by_sig[sigs[i]]]
            evs.sort(key=lambda e: e.ts)
            n += 1
            top = max(evs, key=lambda e: e.rank)
            # representative samples: one per signature, highest severity first
            reps = []
            seen = set()
            for e in sorted(evs, key=lambda e: (-e.rank, e.ts)):
                s = signature(e)
                if s not in seen:
                    seen.add(s)
                    reps.append(e.raw or e.text)
                if len(reps) >= 5:
                    break
            codes = sorted({e.code for e in evs if e.code})
            candidates.append(
                IncidentCandidate(
                    id=f"inc-{n}",
                    system=system,
                    sources=sorted({e.source for e in evs}),
                    level=top.level,
                    count=len(evs),
                    first_ts=evs[0].ts,
                    last_ts=evs[-1].ts,
                    signature=normalize(top.text),
                    samples=reps,
                    codes=codes,
                )
            )
    # most severe, most frequent first
    rank = {"FATAL": 4, "ERROR": 3, "WARN": 2, "WARNING": 2}
    candidates.sort(key=lambda c: (-rank.get(c.level, 1), -c.count))
    for i, c in enumerate(candidates, 1):
        c.id = f"inc-{i}"
    return candidates
