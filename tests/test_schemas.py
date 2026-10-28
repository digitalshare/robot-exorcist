from exorcist.parasail import _strict_schema
from exorcist.schemas import Diagnosis, Verdict, TriageResult


def _walk(node, seen):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            seen.append((node.get("additionalProperties"), set(node["required"]) == set(node["properties"])))
        for v in node.values():
            _walk(v, seen)
    elif isinstance(node, list):
        for v in node:
            _walk(v, seen)


def test_strict_schemas_close_every_object():
    for model in (Diagnosis, Verdict, TriageResult):
        seen = []
        _walk(_strict_schema(model), seen)
        assert seen and all(ap is False and req for ap, req in seen), model.__name__
