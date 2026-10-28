"""Environment-driven configuration. Keys live in .env, never in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PARASAIL_BASE_URL = "https://api.parasail.io/v1"
YOU_SEARCH_URL = "https://ydc-index.io/v1/search"
YOU_CONTENTS_URL = "https://ydc-index.io/v1/contents"


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, "")
    return v.strip() if v and v.strip() else default


@dataclass
class Settings:
    ydc_api_key: str = field(default_factory=lambda: _env("YDC_API_KEY"))
    parasail_api_key: str = field(default_factory=lambda: _env("PARASAIL_API_KEY"))
    parasail_model: str = field(default_factory=lambda: _env("PARASAIL_MODEL", "parasail-qwen3-235b-a22b-instruct-2507"))
    parasail_embed_model: str = field(default_factory=lambda: _env("PARASAIL_EMBED_MODEL", "parasail-bge-m3"))
    parasail_rpm: int = field(default_factory=lambda: int(_env("PARASAIL_RPM", "60")))
    one_secret: str = field(default_factory=lambda: _env("ONE_SECRET"))
    one_connection_keys: str = field(default_factory=lambda: _env("ONE_CONNECTION_KEYS"))
    slack_channel: str = field(default_factory=lambda: _env("SLACK_CHANNEL", "#loft-incident"))
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO"))
    concurrency: int = field(default_factory=lambda: int(_env("EXORCIST_CONCURRENCY", "2")))
    port: int = field(default_factory=lambda: int(_env("EXORCIST_PORT", "8000")))
    cache_dir: Path = field(default_factory=lambda: ROOT / ".cache")

    def missing(self) -> list[str]:
        out = []
        if not self.ydc_api_key:
            out.append("YDC_API_KEY")
        if not self.parasail_api_key:
            out.append("PARASAIL_API_KEY")
        if not self.one_secret:
            out.append("ONE_SECRET")
        return out


settings = Settings()
