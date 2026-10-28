#!/usr/bin/env bash
# One command: install, check keys, start the console, open the browser.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v npx >/dev/null || { echo "Node.js (npx) is required for One's MCP server (@withone/mcp)"; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env — fill in YDC_API_KEY, PARASAIL_API_KEY, ONE_SECRET, GITHUB_REPO, SLACK_CHANNEL and re-run."; exit 1; }
uv sync --quiet
PORT="${EXORCIST_PORT:-8700}"
( sleep 1.5; command -v open >/dev/null && open "http://127.0.0.1:$PORT" || command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT" || true ) &
exec uv run exorcist serve --port "$PORT"
