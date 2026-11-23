#!/usr/bin/env bash
set -euo pipefail

export ANONYMIZED_TELEMETRY=false

echo "==> Syncing Python 3.12 environment with uv"
uv sync --python 3.12 --frozen 2>/dev/null || uv sync --python 3.12

echo "==> Ensuring Playwright Chromium is installed"
uv run playwright install chromium

echo "==> Running offline unit and Playwright integration tests"
uv run pytest -v

if [[ -n "${GOOGLE_API_KEY:-}" ]]; then
  echo "==> GOOGLE_API_KEY detected; running full Gemini 3.5 Flash Lite benchmark (3 runs/group)"
  uv run python -m devbooks_agent.benchmark --runs 3
else
  echo "==> GOOGLE_API_KEY not set; running offline Playwright v1/v2 benchmark (3 runs/group)"
  uv run python -m devbooks_agent.benchmark --runs 3 --groups playwright_v1 playwright_v2 --no-judge-demo
  echo "    Export GOOGLE_API_KEY and re-run ./reproduce.sh to reproduce live Gemini 3.5 Flash Lite runs."
fi
