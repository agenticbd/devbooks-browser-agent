"""Offline deterministic unit and Playwright integration tests for DevBooks Agent."""
from __future__ import annotations

import asyncio
import json
import tempfile
import urllib.request

from playwright.async_api import async_playwright

from demo_site.server import DevBooksServer, ground_truth_matches
from devbooks_agent.hybrid_cdp_agent import find_free_port
from devbooks_agent.models import BookMatch, CatalogReport, reports_match_ground_truth
from devbooks_agent.playwright_scraper import login_with_playwright, run_playwright_scraper


def test_ground_truth_matches_expected_books() -> None:
    gt = ground_truth_matches()
    titles = sorted(b["title"] for b in gt["books"])
    assert titles == [
        "Fast Python CLI Tools",
        "Fluent Async Python",
        "High-Throughput Python APIs",
    ]
    assert gt["total_cost_usd"] == 112.5


def test_report_comparison_ignores_order() -> None:
    gt = ground_truth_matches()
    reversed_books = [BookMatch(**b) for b in reversed(gt["books"])]
    report = CatalogReport(
        query_summary="Python under $45, rating >= 4.5",
        books=reversed_books,
        total_cost_usd=112.50,
    )
    assert reports_match_ground_truth(report, gt) is True


def test_playwright_scraper_passes_on_v1() -> None:
    with DevBooksServer(layout="v1") as srv:
        res = asyncio.run(run_playwright_scraper(srv.base_url, timeout_ms=5000))
    assert res.error is None
    assert res.report is not None
    assert reports_match_ground_truth(res.report, ground_truth_matches())


def test_playwright_scraper_breaks_on_v2_layout() -> None:
    with DevBooksServer(layout="v2") as srv:
        res = asyncio.run(run_playwright_scraper(srv.base_url, timeout_ms=2000))
    assert res.report is None
    assert res.error is not None
    assert "TimeoutError" in res.error
    assert "#category-select" in res.error


def test_playwright_cdp_endpoint_exposes_devtools_json_and_shares_session() -> None:
    async def _check() -> tuple[dict, list[str]]:
        port = find_free_port()
        with DevBooksServer(layout="v2") as srv, tempfile.TemporaryDirectory() as profile_dir:
            async with async_playwright() as pw:
                ctx = await pw.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=True,
                    args=[f"--remote-debugging-port={port}"],
                )
                try:
                    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                    await login_with_playwright(page, srv.base_url)
                    assert "/catalog" in page.url
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as resp:
                        info = json.load(resp)
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/json/new?{srv.base_url}/catalog",
                        method="PUT",
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        tab = json.load(resp)
                    await asyncio.sleep(0.3)
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as resp:
                        tabs = json.load(resp)
                    urls = [t["url"] for t in tabs if t["id"] == tab["id"]]
                    return info, urls
                finally:
                    await ctx.close()

    info, urls = asyncio.run(_check())
    assert "webSocketDebuggerUrl" in info
    assert "Browser" in info
    assert urls and urls[0].endswith("/catalog")
