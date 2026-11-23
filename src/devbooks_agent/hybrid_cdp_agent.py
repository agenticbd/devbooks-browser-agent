"""Hybrid pattern: Playwright handles launch, auth, and verification; Browser Use 1.0 attaches via CDP."""
from __future__ import annotations

import asyncio
import os
import socket
import tempfile
import time
from pathlib import Path

os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")

from browser_use import Agent, Browser
from playwright.async_api import async_playwright

from devbooks_agent.browser_use_agent import (
    DEFAULT_MODEL,
    AgentRunMetrics,
    build_llm,
    build_tools,
    extract_token_counts,
)
from devbooks_agent.models import CatalogReport
from devbooks_agent.playwright_scraper import login_with_playwright


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_catalog_only_task(base_url: str) -> str:
    return (
        f"The browser is already signed in at {base_url}/catalog. Do not log out. "
        "Find ALL books in the 'Python' category/topic priced strictly under $45.00 "
        "with a rating of 4.5 or higher. Check every page of paginated results (do not stop on page 1 if "
        "there is a next page / more titles link). For each matching book, open its detail page to read its "
        "exact ISBN and whether it is currently in stock (true/false). Invoke the verify_total_cost tool "
        "(as a direct tool call, not inside Python REPL code) with the prices of the matching books, then "
        "return the final structured CatalogReport."
    )


async def run_hybrid_cdp_agent(
    base_url: str,
    layout: str = "v2",
    model: str = DEFAULT_MODEL,
    max_steps: int = 20,
    judge: bool = False,
    screenshot_path: Path | None = None,
) -> AgentRunMetrics:
    """Launch Chromium with Playwright, sign in deterministically, then attach Browser Use via CDP."""
    started = time.perf_counter()
    cdp_port = find_free_port()
    cdp_url = f"http://127.0.0.1:{cdp_port}"

    with tempfile.TemporaryDirectory(prefix="devbooks-chrome-profile-") as profile_dir:
        async with async_playwright() as pw:
            # launch_persistent_context uses Chrome's default BrowserContext so login
            # cookies are shared with tabs opened later by browser-use over CDP.
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=True,
                viewport={"width": 1280, "height": 900},
                args=[f"--remote-debugging-port={cdp_port}"],
            )
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                page.set_default_timeout(5000)

                # Step 1: Deterministic login with Playwright (credentials never enter the LLM prompt)
                await login_with_playwright(page, base_url)

                # Step 2: Hand the authenticated browser to Browser Use 1.0 over CDP
                with tempfile.TemporaryDirectory(prefix="devbooks-hybrid-") as workspace:
                    agent = Agent(
                        task=make_catalog_only_task(base_url),
                        llm=build_llm(model),
                        browser=Browser(cdp_url=cdp_url, keep_alive=True),
                        tools=build_tools(),
                        output_model_schema=CatalogReport,
                        mode="ultrafast",
                        reasoning="low",
                        workspace=workspace,
                        judge=judge,
                    )
                    result = await agent.run(max_steps=max_steps, timeout=180)

                # Step 3: Post-run verification and screenshot via Playwright
                active_pages = context.pages
                last_page = active_pages[-1] if active_pages else page
                final_url = last_page.url
                shot_bytes: int | None = None
                if screenshot_path is not None:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    raw = await last_page.screenshot(path=str(screenshot_path), full_page=True)
                    shot_bytes = len(raw)

                elapsed = time.perf_counter() - started
                inp, out = extract_token_counts(getattr(result, "usage", None))
                judgement_obj = getattr(result, "judgement", None)
                judgement_dict = (
                    judgement_obj.model_dump()
                    if hasattr(judgement_obj, "model_dump")
                    else (judgement_obj if isinstance(judgement_obj, dict) else None)
                )
                return AgentRunMetrics(
                    mode="hybrid_cdp",
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
                    final_url=final_url,
                    screenshot_bytes=shot_bytes,
                )
            finally:
                await context.close()


if __name__ == "__main__":
    from dotenv import find_dotenv, load_dotenv
    from demo_site.server import DevBooksServer

    load_dotenv(find_dotenv())
    with DevBooksServer(layout="v2") as srv:
        metrics = asyncio.run(
            run_hybrid_cdp_agent(
                srv.base_url,
                layout="v2",
                screenshot_path=Path("artifacts/hybrid_final.png"),
            )
        )
        print(metrics)
