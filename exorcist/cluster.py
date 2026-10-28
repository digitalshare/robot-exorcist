"""Turn WARN+ log events into incident candidates: embed unique signatures (Parasail), agglomerate by cosine."""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

import numpy as np

from .logs import LogEvent, normalize, signature, interesting
from .schemas import IncidentCandidate

Embedder = Callable[[list[str]], list[list[float]]]


def _agglomerate(vecs: np.ndarray, threshold: float) -> list[int]:
    """Average-linkage agglomerative clustering on cosine similarity. Small n, so O(n^3) is fine."""
    n = len(vecs)
    if n == 0:
        return []
    v = vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-9)
    clusters: list[list[int]] = [[i] for i in range(n)]
    while len(clusters) > 1:
        best, bi, bj = -1.0, -1, -1
        cents = [v[c].mean(axis=0) for c in clusters]
        cents = [c / (np.linalg.norm(c) + 1e-9) for c in cents]
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                s = float(cents[i] @ cents[j])
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


def build_candidates(events: list[LogEvent], embedder: Embedder, *, threshold: float = 0.86, per_system: bool = True) -> list[IncidentCandidate]:
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

    # cluster within each system (a UR fault and an AMR fault are different incidents even if the words rhyme)
    groups: dict[str, list[int]] = defaultdict(list)
    for i, s in enumerate(sigs):
        groups[by_sig[s][0].system if per_system else "all"].append(i)

    candidates: list[IncidentCandidate] = []
    n = 0
    for system, idxs in groups.items():
        labels = _agglomerate(vecs[idxs], threshold)
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
