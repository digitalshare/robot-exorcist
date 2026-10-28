"""Deterministic One executor: drives the same @withone/mcp tools through the MCP Python client.
Used for the smoke test and as the fallback if the Field Tech agent fails to carry out an approved action."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import settings


def _params() -> StdioServerParameters:
    env = {"ONE_SECRET": settings.one_secret, "ONE_PERMISSIONS": "write", "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")}
    if settings.one_connection_keys:
        env["ONE_CONNECTION_KEYS"] = settings.one_connection_keys
    return StdioServerParameters(command="npx", args=["-y", "@withone/mcp"], env=env)


def _text(result) -> Any:
    parts = []
    for c in result.content:
        if getattr(c, "type", "") == "text":
            parts.append(c.text)
    raw = "\n".join(parts)
    try:
        return json.loads(raw)
    except Exception:
        return raw


async def _call(session: ClientSession, name: str, args: dict) -> Any:
    return _text(await session.call_tool(name, args))


async def list_integrations() -> Any:
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            return {"tools": tools, "integrations": await _call(s, "list_one_integrations", {})}


def _find_connection(integrations: Any, platform: str) -> str | None:
    blob = json.dumps(integrations).lower()
    if platform not in blob:
        return None
    # walk for dicts mentioning the platform with a connection key
    stack = [integrations]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            vals = json.dumps(node).lower()
            if platform in vals:
                for k in ("connection_key", "connectionKey", "key"):
                    if isinstance(node.get(k), str) and platform in vals:
                        return node[k]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


async def execute(kind: str, title: str, body: str) -> dict:
    """kind: slack_alert | github_issue. Returns {ok, url, note, raw}."""
    async with stdio_client(_params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            integrations = await _call(s, "list_one_integrations", {})
            platform = "slack" if kind == "slack_alert" else "github"
            conn = _find_connection(integrations, platform)
            if not conn:
                return {"ok": False, "url": None, "note": f"no {platform} connection in One", "raw": integrations}
            intent = "post a message to a channel" if platform == "slack" else "create an issue in a repository"
            found = await _call(s, "find_one_actions", {"requests": [{"platform": platform, "intent": intent}], "task": f"{intent} ({title})"})
            action_id = _first_action_id(found)
            if not action_id:
                return {"ok": False, "url": None, "note": "no action id found", "raw": found}
            if platform == "slack":
                args = {"action_id": action_id, "connection_key": conn, "data": {"channel": settings.slack_channel, "text": body}}
            else:
                owner, _, repo = settings.github_repo.partition("/")
                args = {"action_id": action_id, "connection_key": conn, "path_variables": {"owner": owner, "repo": repo}, "data": {"title": title, "body": body}}
            res = await _call(s, "execute_one_action", args)
            return {"ok": _looks_ok(res), "url": _extract_url(res, platform), "note": "", "raw": res}


def _first_action_id(found: Any) -> str | None:
    stack = [found]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            for k in ("action_id", "actionId", "id"):
                if isinstance(node.get(k), str) and ("." in node[k] or "_" in node[k] or "-" in node[k]):
                    return node[k]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return None


def _looks_ok(res: Any) -> bool:
    blob = json.dumps(res).lower() if not isinstance(res, str) else res.lower()
    if '"ok": false' in blob or '"ok":false' in blob or "error" in blob[:200]:
        return False
    return True


def _extract_url(res: Any, platform: str) -> str | None:
    stack = [res]
    while stack:
        node = stack.pop(0)
        if isinstance(node, dict):
            for k in ("html_url", "permalink", "url"):
                v = node.get(k)
                if isinstance(v, str) and v.startswith("http") and ("github.com" in v if platform == "github" else True):
                    return v
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    if platform == "slack" and isinstance(res, dict):
        ch, ts = res.get("channel"), res.get("ts")
        if ch and ts:
            return f"slack://channel?id={ch}&message={ts}"
    return None


def run(coro):
    return asyncio.run(coro)
