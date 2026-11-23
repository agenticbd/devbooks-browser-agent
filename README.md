# DevBooks Browser Agent

Companion project comparing three Python web-automation patterns against a local multi-page catalog app (`DevBooks Catalog`) with a switchable `v1` / `v2` DOM redesign:

1. **Pure Playwright (`playwright==1.65.2`)**: fast, deterministic, zero-token baseline that breaks when `v2` renames selectors and moves filters into a drawer.
2. **Standalone Browser Use 1.0 (`browser-use==1.0.8`) + Gemini 3.5 Flash Lite (`gemini-3.5-flash-lite`)**: Pydantic AI REPL + CDP agent with typed `CatalogReport` output and a custom `@tools.action` helper.
3. **Hybrid Playwright + Browser Use over CDP**: Playwright launches Chromium with `--remote-debugging-port`, logs in deterministically (keeping credentials out of the LLM prompt), hands off the browser via `Browser(cdp_url=..., keep_alive=True)`, and captures a post-run verification screenshot.

## Quickstart

```bash
cp .env.example .env
# Edit .env and add GOOGLE_API_KEY

uv sync --python 3.12
uv run playwright install chromium
uv run pytest -v
uv run python -m devbooks_agent.benchmark --runs 3
```

Or run everything via `./reproduce.sh`.
