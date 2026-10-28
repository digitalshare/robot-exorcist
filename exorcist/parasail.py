"""Parasail: OpenAI-compatible chat (schema-locked JSON) and embeddings, with a client-side RPM throttle."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import Any, TypeVar

from openai import OpenAI, RateLimitError, APIStatusError
from pydantic import BaseModel

from .config import PARASAIL_BASE_URL, settings

T = TypeVar("T", bound=BaseModel)


class _Throttle:
    """Token bucket: at most `rpm` requests in any rolling 60 s window. Shared by every Parasail call in the process."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def wait(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] > 60:
                    self.calls.popleft()
                if len(self.calls) < self.rpm:
                    self.calls.append(now)
                    return
                sleep_for = 60 - (now - self.calls[0]) + 0.05
            time.sleep(min(sleep_for, 5))


throttle = _Throttle(settings.parasail_rpm)

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=PARASAIL_BASE_URL, api_key=settings.parasail_api_key, max_retries=0, timeout=120)
    return _client


def _strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema → strict JSON schema (additionalProperties false everywhere, all props required)."""
    schema = model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in node.values():
                tighten(v)
        elif isinstance(node, list):
            for v in node:
                tighten(v)

    tighten(schema)
    return schema


def _with_retries(fn, *, tries: int = 5):
    delay = 2.0
    for attempt in range(tries):
        throttle.wait()
        try:
            return fn()
        except RateLimitError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
        except APIStatusError as e:
            if e.status_code >= 500 and attempt < tries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise


def chat_json(system: str, user: str, schema_model: type[T], *, model: str | None = None, temperature: float = 0.1, max_tokens: int = 4000) -> T:
    """One schema-locked completion. Parasail enforces the schema server-side; we still validate with pydantic."""
    name = schema_model.__name__
    schema = _strict_schema(schema_model)

    def call():
        return client().chat.completions.create(
            model=model or settings.parasail_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )

    resp = _with_retries(call)
    content = resp.choices[0].message.content or "{}"
    # Some reasoning models wrap JSON in <think> blocks or fences; strip defensively.
    if "</think>" in content:
        content = content.split("</think>", 1)[1]
    content = content.strip().strip("`")
    if content.startswith("json"):
        content = content[4:]
    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end != -1:
        content = content[start : end + 1]
    return schema_model.model_validate(json.loads(content))


def embed(texts: list[str], *, model: str | None = None, batch: int = 64) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = texts[i : i + batch]
        resp = _with_retries(lambda: client().embeddings.create(model=model or settings.parasail_embed_model, input=chunk))
        out.extend([d.embedding for d in sorted(resp.data, key=lambda d: d.index)])
    return out


def list_models() -> list[str]:
    throttle.wait()
    return sorted(m.id for m in client().models.list().data)
