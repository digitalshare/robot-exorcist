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
