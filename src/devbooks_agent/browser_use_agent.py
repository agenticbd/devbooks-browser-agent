"""Standalone Browser Use 1.0 agent powered by Gemini 3.5 Flash Lite."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

from browser_use import Agent, Browser, ChatGoogle, Tools
from google.genai import types
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from demo_site.server import DEMO_EMAIL, DEMO_PASSWORD
from devbooks_agent.models import CatalogReport

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def build_llm(model: str = DEFAULT_MODEL, resilient: bool = True) -> Any:
    """Return a Gemini LLM for browser-use 1.0.

    ChatGoogle(model) works out of the box, but under transient 503 demand spikes
    passing a Pydantic AI GoogleModel with HttpRetryOptions retries mid-run
    without discarding the browser REPL session.
    """
    if not resilient:
        return ChatGoogle(model)
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    retry_options = types.HttpRetryOptions(
        attempts=5,
        initial_delay=1.5,
        max_delay=8.0,
        exp_base=2.0,
        http_status_codes=[429, 500, 502, 503, 504],
    )
    return GoogleModel(
        model,
        provider=GoogleProvider(api_key=api_key, retry_options=retry_options),
        settings={
            "max_retries": 4,
            "google_thinking_config": {"thinking_level": "LOW"},
        },
    )


@dataclass
class AgentRunMetrics:
    mode: str
    layout: str
    status: str
    report: CatalogReport | None
    duration_seconds: float
    steps: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    judgement: dict[str, Any] | None = None
    error: str | None = None
    final_url: str | None = None
    screenshot_bytes: int | None = None


def build_tools() -> Tools:
    """Create custom Python tools exposed to the Browser Use 1.0 agent."""
    tools = Tools()

    @tools.action("Sum a list of USD book prices and return the exact total rounded to 2 decimals")
    def verify_total_cost(prices: list[float]) -> str:
        total = round(sum(float(p) for p in prices), 2)
        return f"{total:.2f}"

    return tools


def extract_token_counts(usage: Any) -> tuple[int, int]:
    """Read input and output token totals from browser-use 1.0 result.usage."""
    if not usage:
        return 0, 0
    if isinstance(usage, dict):
        inp = int(usage.get("input", usage.get("input_tokens", 0)) or 0)
        out = int(usage.get("output", usage.get("output_tokens", 0)) or 0)
        return inp, out
    inp = int(getattr(usage, "input_tokens", getattr(usage, "input", 0)) or 0)
    out = int(getattr(usage, "output_tokens", getattr(usage, "output", 0)) or 0)
    return inp, out


def make_standalone_task(base_url: str) -> str:
    return (
        f"Go to {base_url}/login and sign in with email '{DEMO_EMAIL}' and password '{DEMO_PASSWORD}'. "
        "Once on the catalog page, find ALL books in the 'Python' category/topic priced strictly under $45.00 "
        "with a rating of 4.5 or higher. Check every page of paginated results (do not stop on page 1 if "
        "there is a next page / more titles link). For each matching book, open its detail page to read its "
        "exact ISBN and whether it is currently in stock (true/false). Invoke the verify_total_cost tool "
        "(as a direct tool call, not inside Python REPL code) with the prices of the matching books, then "
        "return the final structured CatalogReport."
    )


async def run_browser_use_agent(
    base_url: str,
    layout: str,
    model: str = DEFAULT_MODEL,
    max_steps: int = 20,
    judge: bool = False,
) -> AgentRunMetrics:
    """Run a standalone Browser Use 1.0 agent in a fresh headless Chromium browser."""
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="devbooks-bu-") as workspace:
        agent = Agent(
            task=make_standalone_task(base_url),
            llm=build_llm(model),
            browser=Browser("chromium", headless=True),
            tools=build_tools(),
            output_model_schema=CatalogReport,
            mode="ultrafast",
            reasoning="low",
            workspace=workspace,
            judge=judge,
        )
        result = await agent.run(max_steps=max_steps, timeout=180)
        elapsed = time.perf_counter() - started
        inp, out = extract_token_counts(getattr(result, "usage", None))
        judgement_obj = getattr(result, "judgement", None)
        judgement_dict = (
            judgement_obj.model_dump()
            if hasattr(judgement_obj, "model_dump")
            else (judgement_obj if isinstance(judgement_obj, dict) else None)
        )
        return AgentRunMetrics(
            mode="browser_use",
            layout=layout,
            status=str(getattr(result, "status", "unknown")),
            report=getattr(result, "structured_output", None),
            duration_seconds=elapsed,
            steps=int(result.number_of_steps()),
            input_tokens=inp,
            output_tokens=out,
            cost_usd=getattr(result, "cost_usd", None),
            judgement=judgement_dict,
            error=str(result.error) if getattr(result, "error", None) else None,
        )


if __name__ == "__main__":
    from dotenv import find_dotenv, load_dotenv
    from demo_site.server import DevBooksServer

    load_dotenv(find_dotenv())
    with DevBooksServer(layout="v2") as srv:
        metrics = asyncio.run(run_browser_use_agent(srv.base_url, layout="v2"))
        print(metrics)
