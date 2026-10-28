import hashlib
import numpy as np
from exorcist.logs import load_scenario
from exorcist.cluster import build_candidates


def fake_embedder(texts):
    """Deterministic bag-of-words embedding so clustering is testable offline."""
    vocab = {}
    rows = []
    for t in texts:
        toks = [w for w in t.lower().replace("[", " ").replace("]", " ").split() if w.isalpha()]
        rows.append(toks)
        for w in toks:
            vocab.setdefault(w, len(vocab))
    out = []
    for toks in rows:
        v = np.zeros(max(len(vocab), 1))
        for w in toks:
            v[vocab[w]] += 1
        out.append(v.tolist())
    return out


def test_candidates_group_by_system_and_rank_errors_first():
    _, events = load_scenario("samples/haunted_cell")
    cands = build_candidates(events, fake_embedder, threshold=0.5)
    assert 3 <= len(cands) <= 7, [c.signature for c in cands]
    assert cands, "expected incident candidates"
    assert cands[0].level == "ERROR"
    systems = {c.system for c in cands}
    assert systems == {"ur5e", "gripper", "amr"}
    tf = [c for c in cands if "TF_REPEATED_DATA" in " ".join(c.samples)]
    assert tf and tf[0].level == "WARN"
    assert all(c.count >= 1 for c in cands)
    assert [c.id for c in cands] == [f"inc-{i}" for i in range(1, len(cands) + 1)]
