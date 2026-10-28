"""CrewAI tools wrapping You.com. The Researcher agent's only way to learn anything about the fault."""
from __future__ import annotations

import json
from typing import Callable

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from . import you

Observer = Callable[[str, dict], None]


class SearchInput(BaseModel):
    query: str = Field(description="A focused web search query, e.g. 'UR5e C204A0 protective stop position deviates from path cause'")


class ReadInput(BaseModel):
    url: str = Field(description="A URL returned by you_search")


class YouSearchTool(BaseTool):
    name: str = "you_search"
    description: str = "Search the web (You.com) for vendor manuals, error-code references, GitHub issues and ROS Answers threads. Returns JSON results with url, title and highlight snippets."
    args_schema: type[BaseModel] = SearchInput
    incident_id: str = ""
    observer: Observer | None = None

    def _run(self, query: str) -> str:
        try:
            results = you.search(query, count=6)
        except Exception as e:  # tool errors must come back as text so the agent can recover
            return f"search failed: {e}"
        if self.observer:
            self.observer("search", {"incident_id": self.incident_id, "query": query, "results": results})
        slim = [{"url": r["url"], "title": r["title"], "snippets": r["snippets"][:3]} for r in results]
        return json.dumps(slim, ensure_ascii=False)


class YouReadTool(BaseTool):
    name: str = "you_read"
    description: str = "Read a web page (You.com Contents) as markdown. Use it on the 2-3 most promising you_search results to pull exact quotes."
    args_schema: type[BaseModel] = ReadInput
    incident_id: str = ""
    observer: Observer | None = None

    def _run(self, url: str) -> str:
        try:
            page = you.contents(url)
        except Exception as e:
            return f"read failed for {url}: {e}"
        if self.observer:
            self.observer("read", {"incident_id": self.incident_id, "url": url, "title": page["title"], "chars": len(page["markdown"])})
        return f"# {page['title']}\n{url}\n\n{page['markdown']}"


def make_tools(incident_id: str, observer: Observer | None = None) -> list[BaseTool]:
    return [YouSearchTool(incident_id=incident_id, observer=observer), YouReadTool(incident_id=incident_id, observer=observer)]


# ---------------------------------------------------------------- One (actions)
# The Field Tech agent gets two narrow tools. Each one drives One's MCP server
# (find_one_actions -> execute_one_action) and returns the upstream result, so the
# URL the agent reports is the URL One returned, never an invention.


class SlackInput(BaseModel):
    text: str = Field(description="The full alert text to post (Slack mrkdwn allowed)")


class IssueInput(BaseModel):
    title: str = Field(description="Issue title")
    body: str = Field(description="Issue body in Markdown")


class OneSlackTool(BaseTool):
    name: str = "post_slack_alert"
    description: str = "Post an alert message to the team's incident Slack channel through One. Returns JSON {ok, url, note}."
    args_schema: type[BaseModel] = SlackInput
    observer: Observer | None = None

    def _run(self, text: str) -> str:
        from . import one_exec

        try:
            r = one_exec.run(one_exec.execute("slack_alert", "alert", text))
        except Exception as e:
            r = {"ok": False, "url": None, "note": f"{type(e).__name__}: {e}"}
        out = {"ok": bool(r.get("ok")), "url": r.get("url"), "note": r.get("note") or ""}
        if not out["ok"] and r.get("raw") is not None:
            out["note"] = (out["note"] + " " + json.dumps(r["raw"])[:400]).strip()
        if self.observer:
            self.observer("action_result", {"kind": "slack_alert", **out, "text": text})
        return json.dumps(out)


class OneGitHubTool(BaseTool):
    name: str = "open_github_issue"
    description: str = "Open a GitHub issue in the team's robot repository through One. Returns JSON {ok, url, note}."
    args_schema: type[BaseModel] = IssueInput
    observer: Observer | None = None

    def _run(self, title: str, body: str) -> str:
        from . import one_exec

        try:
            r = one_exec.run(one_exec.execute("github_issue", title, body))
        except Exception as e:
            r = {"ok": False, "url": None, "note": f"{type(e).__name__}: {e}"}
        out = {"ok": bool(r.get("ok")), "url": r.get("url"), "note": r.get("note") or ""}
        if not out["ok"] and r.get("raw") is not None:
            out["note"] = (out["note"] + " " + json.dumps(r["raw"])[:400]).strip()
        if self.observer:
            self.observer("action_result", {"kind": "github_issue", **out, "title": title, "body": body})
        return json.dumps(out)


def make_action_tools(observer: Observer | None = None) -> list[BaseTool]:
    return [OneSlackTool(observer=observer), OneGitHubTool(observer=observer)]
