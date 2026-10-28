"""You.com Search + Contents. Grounding only: no model calls here."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from .config import YOU_CONTENTS_URL, YOU_SEARCH_URL, settings

MAX_PAGE_CHARS = 6000


def _headers() -> dict:
    return {"X-API-Key": settings.ydc_api_key, "Content-Type": "application/json"}


def search(query: str, count: int = 6) -> list[dict]:
    """Web search with highlight extraction. Returns [{url,title,description,snippets[],page_age}]."""
    body = {"query": query, "count": count, "extraction": {"extraction_mode": "highlights"}}
    with httpx.Client(timeout=30) as c:
        r = c.post(YOU_SEARCH_URL, headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()
    results = []
    for w in (data.get("results") or {}).get("web") or []:
        contents = w.get("contents") or {}
        highlights = contents.get("highlights") or []
        snippets = list(w.get("snippets") or [])
        if highlights:
            snippets = [h if isinstance(h, str) else h.get("text", "") for h in highlights] + snippets
        results.append(
            {
                "url": w.get("url", ""),
                "title": w.get("title", ""),
                "description": w.get("description", ""),
                "snippets": [s for s in snippets if s][:4],
                "page_age": w.get("page_age"),
                "favicon_url": w.get("favicon_url"),
            }
        )
    return results


def _cache_path(url: str) -> Path:
    d = settings.cache_dir / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(url.encode()).hexdigest() + ".json")


def contents(url: str, max_chars: int = MAX_PAGE_CHARS) -> dict:
    """Fetch a page as markdown. Pages are cached on disk (pages do not change during a hackathon; model outputs are never cached)."""
    p = _cache_path(url)
    if p.exists():
        data = json.loads(p.read_text())
    else:
        with httpx.Client(timeout=45) as c:
            r = c.post(YOU_CONTENTS_URL, headers=_headers(), json={"urls": [url], "formats": ["markdown"]})
            r.raise_for_status()
            arr = r.json()
        item = arr[0] if isinstance(arr, list) and arr else (arr if isinstance(arr, dict) else {})
        data = {"url": url, "title": item.get("title") or url, "markdown": item.get("markdown") or ""}
        p.write_text(json.dumps(data))
    md = data.get("markdown") or ""
    return {"url": url, "title": data.get("title") or url, "markdown": md[:max_chars], "truncated": len(md) > max_chars}
