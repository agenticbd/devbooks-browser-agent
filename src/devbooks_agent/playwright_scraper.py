"""Deterministic Playwright scraper written against the v1 DevBooks DOM."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import Page, async_playwright

from demo_site.server import DEMO_EMAIL, DEMO_PASSWORD
from devbooks_agent.models import BookMatch, CatalogReport


@dataclass
class ScraperResult:
    report: CatalogReport | None
    duration_seconds: float
    error: str | None = None


async def login_with_playwright(
    page: Page,
    base_url: str,
    email: str = DEMO_EMAIL,
    password: str = DEMO_PASSWORD,
) -> None:
    """Sign in deterministically on /login and wait for the /catalog redirect."""
    await page.goto(f"{base_url}/login", wait_until="domcontentloaded")
    await page.fill("#email", email)
    await page.fill("#password", password)
    await page.click("#login-submit")
    await page.wait_for_url("**/catalog**")


async def run_playwright_scraper(base_url: str, timeout_ms: int = 5000) -> ScraperResult:
    """Scrape Python books priced under $45 with rating >= 4.5 using v1 selectors."""
    started = time.perf_counter()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                page.set_default_timeout(timeout_ms)

                await login_with_playwright(page, base_url)

                # v1 catalog selectors: intentionally coupled to the v1 DOM
                await page.select_option("#category-select", "Python")
                await page.fill("#max-price", "45")
                await page.click("#apply-filters")
                await page.wait_for_selector("article.book-card")

                candidate_urls: list[tuple[str, float, float, str]] = []
                while True:
                    cards = page.locator("article.book-card")
                    count = await cards.count()
                    for idx in range(count):
                        card = cards.nth(idx)
                        title = (await card.locator(".book-title").inner_text()).strip()
                        price_text = (await card.locator(".book-price").inner_text()).strip()
                        rating_text = (await card.locator(".book-rating").inner_text()).strip()
                        href = await card.locator("a.book-link").get_attribute("href")
                        price = float(price_text.replace("$", ""))
                        rating = float(rating_text)
                        if price < 45.0 and rating >= 4.5 and href:
                            candidate_urls.append((title, price, rating, href))

                    next_link = page.locator("a.next-page")
                    if await next_link.count() > 0:
                        await next_link.click()
                        await page.wait_for_selector("article.book-card")
                    else:
                        break

                books: list[BookMatch] = []
                for title, price, rating, href in candidate_urls:
                    await page.goto(f"{base_url}{href}", wait_until="domcontentloaded")
                    isbn = (await page.locator(".detail-isbn").inner_text()).strip()
                    stock_text = (await page.locator(".detail-stock").inner_text()).strip().lower()
                    books.append(
                        BookMatch(
                            title=title,
                            price_usd=price,
                            rating=rating,
                            isbn=isbn,
                            in_stock=(stock_text == "in stock"),
                        )
                    )

                total_cost = round(sum(b.price_usd for b in books), 2)
                report = CatalogReport(
                    query_summary="Python books under $45.00 with rating >= 4.5",
                    books=books,
                    total_cost_usd=total_cost,
                )
                return ScraperResult(report=report, duration_seconds=time.perf_counter() - started)
            finally:
                await browser.close()
    except Exception as exc:
        return ScraperResult(
            report=None,
            duration_seconds=time.perf_counter() - started,
            error=f"{type(exc).__name__}: {exc}",
        )


if __name__ == "__main__":
    from demo_site.server import DevBooksServer

    with DevBooksServer(layout="v1") as srv:
        res = asyncio.run(run_playwright_scraper(srv.base_url))
        print(res)
