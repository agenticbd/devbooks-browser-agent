"""Local multi-page bookstore app with switchable v1 and v2 DOM layouts.

Run directly:
    python -m demo_site.server --layout v1 --port 8765
    python -m demo_site.server --layout v2 --port 8765
"""
from __future__ import annotations

import argparse
import html
import json
import math
import threading
from dataclasses import asdict, dataclass
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

DEMO_EMAIL = "demo@devbooks.local"
DEMO_PASSWORD = "reader-2026"
SESSION_COOKIE = "devbooks_session"
SESSION_TOKEN = "authenticated-reader-2026"
PAGE_SIZE = 3


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    category: str
    price_usd: float
    rating: float
    isbn: str
    in_stock: bool
    edition_year: int
    summary: str


CATALOG: list[Book] = [
    Book(
        id=1,
        title="Fluent Async Python",
        category="Python",
        price_usd=39.00,
        rating=4.8,
        isbn="978-1-4920-5635-1",
        in_stock=True,
        edition_year=2025,
        summary="Structured concurrency, asyncio internals, and cancellation patterns.",
    ),
    Book(
        id=2,
        title="Rust for Network Engineers",
        category="Systems",
        price_usd=42.50,
        rating=4.7,
        isbn="978-1-7185-0310-6",
        in_stock=True,
        edition_year=2025,
        summary="Building low-latency packet tools and async proxies in Rust.",
    ),
    Book(
        id=3,
        title="Practical Playwright Testing",
        category="Web",
        price_usd=34.00,
        rating=4.6,
        isbn="978-1-8010-7922-4",
        in_stock=True,
        edition_year=2026,
        summary="End-to-end browser verification, fixtures, and trace debugging.",
    ),
    Book(
        id=4,
        title="Python Typing in Production",
        category="Python",
        price_usd=48.00,
        rating=4.9,
        isbn="978-1-0981-2244-7",
        in_stock=True,
        edition_year=2026,
        summary="Static type checking, protocols, and Pydantic validation at scale.",
    ),
    Book(
        id=5,
        title="Fast Python CLI Tools",
        category="Python",
        price_usd=29.50,
        rating=4.5,
        isbn="978-1-4842-8811-5",
        in_stock=False,
        edition_year=2024,
        summary="Packaging, argument parsing, and fast startup times for terminal apps.",
    ),
    Book(
        id=6,
        title="SQL Query Tuning",
        category="Data",
        price_usd=36.00,
        rating=4.4,
        isbn="978-1-4920-7741-7",
        in_stock=True,
        edition_year=2024,
        summary="Index selection, execution plans, and lock contention diagnosis.",
    ),
    Book(
        id=7,
        title="Python Packaging Quickstart",
        category="Python",
        price_usd=24.00,
        rating=4.2,
        isbn="978-1-8350-4119-0",
        in_stock=True,
        edition_year=2025,
        summary="Modern pyproject.toml builds, wheels, and lockfiles with uv.",
    ),
    Book(
        id=8,
        title="High-Throughput Python APIs",
        category="Python",
        price_usd=44.00,
        rating=4.7,
        isbn="978-1-0981-6502-4",
        in_stock=True,
        edition_year=2026,
        summary="Profiling ASGI services, connection pools, and backpressure.",
    ),
    Book(
        id=9,
        title="Browser Internals & CDP",
        category="Web",
        price_usd=41.00,
        rating=4.8,
        isbn="978-1-4920-9012-6",
        in_stock=True,
        edition_year=2026,
        summary="DOM pipelines, accessibility trees, and Chrome DevTools Protocol.",
    ),
    Book(
        id=10,
        title="Modern Data Pipelines",
        category="Data",
        price_usd=38.00,
        rating=4.6,
        isbn="978-1-0981-4430-2",
        in_stock=True,
        edition_year=2025,
        summary="Incremental transforms, schema evolution, and backfill hygiene.",
    ),
]

BOOK_BY_ID: dict[int, Book] = {b.id: b for b in CATALOG}
CATEGORIES = ["All", "Python", "Systems", "Web", "Data"]


def ground_truth_matches(
    category: str = "Python", max_price_exclusive: float = 45.0, min_rating: float = 4.5
) -> dict[str, Any]:
    """Return canonical expected matches for automated evaluation."""
    matches = [
        {
            "title": b.title,
            "price_usd": b.price_usd,
            "rating": b.rating,
            "isbn": b.isbn,
            "in_stock": b.in_stock,
        }
        for b in CATALOG
        if b.category == category
        and b.price_usd < max_price_exclusive
        and b.rating >= min_rating
    ]
    total = round(sum(m["price_usd"] for m in matches), 2)
    return {
        "books": matches,
        "total_cost_usd": total,
    }


def _page_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; color: #1f2937; }}
    header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.75rem; margin-bottom: 1.5rem; }}
    .book-card, .tile-wrap {{ border: 1px solid #d1d5db; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
    .meta {{ color: #4b5563; font-size: 0.92rem; }}
    .error {{ color: #b91c1c; font-weight: 600; }}
    .pager {{ display: flex; gap: 1rem; margin-top: 1.5rem; align-items: center; }}
    .drawer {{ border: 1px dashed #9ca3af; border-radius: 8px; padding: 1rem; margin: 1rem 0; background: #f9fafb; }}
    button, a.btn {{ background: #1d4ed8; color: #fff; border: 0; border-radius: 6px; padding: 0.45rem 0.9rem; cursor: pointer; text-decoration: none; display: inline-block; }}
    input, select {{ padding: 0.4rem; margin-right: 0.5rem; }}
  </style>
</head>
<body>
  <header>
    <strong>DevBooks Catalog</strong>
    <nav><a href="/catalog">Catalog</a></nav>
  </header>
  {body}
</body>
</html>
"""


def _render_login(error: str = "") -> str:
    err_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""
    <h1>Sign in to DevBooks</h1>
    {err_html}
    <form method="post" action="/login" id="login-form">
      <div style="margin-bottom:0.75rem;">
        <label for="email">Email</label><br />
        <input id="email" name="email" type="email" required />
      </div>
      <div style="margin-bottom:0.75rem;">
        <label for="password">Password</label><br />
        <input id="password" name="password" type="password" required />
      </div>
      <button id="login-submit" type="submit">Sign in</button>
    </form>
    """
    return _page_shell("Sign in - DevBooks", body)


def _filter_books(category: str, max_price: float | None) -> list[Book]:
    items = list(CATALOG)
    if category and category != "All":
        items = [b for b in items if b.category.lower() == category.lower()]
    if max_price is not None:
        items = [b for b in items if b.price_usd <= max_price]
    return items


def _render_catalog_v1(category: str, max_price_raw: str, page: int) -> str:
    max_price = float(max_price_raw) if max_price_raw else None
    filtered = _filter_books(category, max_price)
    total_pages = max(1, math.ceil(len(filtered) / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_items = filtered[start : start + PAGE_SIZE]

    options = "".join(
        f'<option value="{c}"{" selected" if c == category else ""}>{c}</option>'
        for c in CATEGORIES
    )

    cards = []
    for b in page_items:
        cards.append(
            f"""
            <article class="book-card" data-book-id="{b.id}">
              <h2 class="book-title">{html.escape(b.title)}</h2>
              <p class="meta">
                Category: <span class="book-category">{html.escape(b.category)}</span> ·
                Price: <span class="book-price">${b.price_usd:.2f}</span> ·
                Rating: <span class="book-rating">{b.rating:.1f}</span>
              </p>
              <a class="book-link" href="/book/{b.id}">Open book details</a>
            </article>
            """
        )

    pager_links = [f'<span class="page-indicator">Page {page} of {total_pages}</span>']
    if page > 1:
        qs = urlencode({"category": category, "max_price": max_price_raw, "page": page - 1})
        pager_links.append(f'<a class="prev-page" href="/catalog?{qs}">Previous</a>')
    if page < total_pages:
        qs = urlencode({"category": category, "max_price": max_price_raw, "page": page + 1})
        pager_links.append(f'<a class="next-page" href="/catalog?{qs}">Next page</a>')

    body = f"""
    <h1>Catalog (v1)</h1>
    <form method="get" action="/catalog" id="filter-form" style="margin-bottom:1.25rem;">
      <label for="category-select">Category:</label>
      <select id="category-select" name="category">{options}</select>
      <label for="max-price">Max price (USD):</label>
      <input id="max-price" name="max_price" type="number" step="0.5" value="{html.escape(max_price_raw)}" placeholder="e.g. 45" />
      <button id="apply-filters" type="submit">Apply filters</button>
    </form>
    <p class="meta">Showing {len(page_items)} of {len(filtered)} matching books.</p>
    <section id="book-list">{"".join(cards) or "<p>No books match your filters.</p>"}</section>
    <div class="pager">{"".join(pager_links)}</div>
    """
    return _page_shell("Catalog (v1) - DevBooks", body)


def _render_catalog_v2(topic: str, price_cap_raw: str, page: int) -> str:
    max_price = float(price_cap_raw) if price_cap_raw else None
    filtered = _filter_books(topic, max_price)
    total_pages = max(1, math.ceil(len(filtered) / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    page_items = filtered[start : start + PAGE_SIZE]

    options = "".join(
        f'<option value="{c}"{" selected" if c == topic else ""}>{c}</option>'
        for c in CATEGORIES
    )

    tiles = []
    for b in page_items:
        tiles.append(
            f"""
            <div class="tile-wrap" data-sku="bk-{b.id}">
              <h3>{html.escape(b.title)}</h3>
              <div class="meta">
                Topic: <em>{html.escape(b.category)}</em> |
                <span class="cost-badge">USD {b.price_usd:.2f}</span> |
                <span class="score-pill">{b.rating:.1f} / 5.0</span>
              </div>
              <p style="margin-top:0.6rem;">
                <a class="inspect-btn btn" href="/book/{b.id}">View Details</a>
              </p>
            </div>
            """
        )

    pager_links = [f'<span>Listing page {page} / {total_pages} ({len(filtered)} total)</span>']
    if page > 1:
        qs = urlencode({"topic": topic, "price_cap": price_cap_raw, "p": page - 1})
        pager_links.append(f'<a class="pager-back" href="/catalog?{qs}">← Earlier titles</a>')
    if page < total_pages:
        qs = urlencode({"topic": topic, "price_cap": price_cap_raw, "p": page + 1})
        pager_links.append(f'<a class="pager-forward" href="/catalog?{qs}">More titles →</a>')

    body = f"""
    <h1>Browse Inventory (v2)</h1>
    <button type="button" id="toggle-drawer" aria-expanded="false">Filter Options</button>
    <div id="filter-drawer" class="drawer" style="display:none;">
      <form method="get" action="/catalog">
        <label for="topic-picker">Topic:</label>
        <select id="topic-picker" name="topic">{options}</select>
        <label for="price-cap">Price cap:</label>
        <input id="price-cap" name="price_cap" type="number" step="0.5" value="{html.escape(price_cap_raw)}" placeholder="45" />
        <button type="submit">Update Results</button>
      </form>
    </div>
    <script>
      document.getElementById("toggle-drawer").addEventListener("click", function () {{
        const panel = document.getElementById("filter-drawer");
        const open = panel.style.display === "block";
        panel.style.display = open ? "none" : "block";
        this.setAttribute("aria-expanded", String(!open));
      }});
    </script>
    <div id="inventory-grid">{"".join(tiles) or "<p>Nothing matched.</p>"}</div>
    <div class="pager">{"".join(pager_links)}</div>
    """
    return _page_shell("Browse Inventory (v2) - DevBooks", body)


def _render_detail_v1(book: Book) -> str:
    stock_text = "In stock" if book.in_stock else "Out of stock"
    body = f"""
    <p><a href="/catalog">← Back to catalog</a></p>
    <h1 class="detail-title">{html.escape(book.title)}</h1>
    <p>{html.escape(book.summary)}</p>
    <ul>
      <li>Category: <span class="detail-category">{html.escape(book.category)}</span></li>
      <li>Price: <span class="detail-price">${book.price_usd:.2f}</span></li>
      <li>Rating: <span class="detail-rating">{book.rating:.1f}</span></li>
      <li>ISBN: <span class="detail-isbn">{html.escape(book.isbn)}</span></li>
      <li>Stock: <span class="detail-stock">{stock_text}</span></li>
      <li>Edition: {book.edition_year}</li>
    </ul>
    """
    return _page_shell(f"{book.title} - DevBooks", body)


def _render_detail_v2(book: Book) -> str:
    stock_text = "Available now" if book.in_stock else "Currently out of stock"
    body = f"""
    <p><a href="/catalog">← Return to inventory</a></p>
    <article data-detail-sku="bk-{book.id}">
      <h2>{html.escape(book.title)}</h2>
      <p>{html.escape(book.summary)}</p>
      <dl class="spec-grid">
        <dt>Topic</dt><dd>{html.escape(book.category)}</dd>
        <dt>Unit Price</dt><dd>USD {book.price_usd:.2f}</dd>
        <dt>Reader Score</dt><dd>{book.rating:.1f} / 5.0</dd>
        <dt>ISBN-13</dt><dd>{html.escape(book.isbn)}</dd>
        <dt>Availability</dt><dd>{stock_text}</dd>
        <dt>Published</dt><dd>{book.edition_year}</dd>
      </dl>
    </article>
    """
    return _page_shell(f"{book.title} - DevBooks", body)


def make_handler(layout: str) -> type[BaseHTTPRequestHandler]:
    class DevBooksHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return  # keep test/benchmark stdout clean

        def _is_authenticated(self) -> bool:
            raw = self.headers.get("Cookie", "")
            jar = cookies.SimpleCookie()
            jar.load(raw)
            morsel = jar.get(SESSION_COOKIE)
            return morsel is not None and morsel.value == SESSION_TOKEN

        def _send_html(self, content: str, status: int = 200) -> None:
            data = content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            data = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _redirect(self, location: str, status: int = 302, extra_headers: list[tuple[str, str]] | None = None) -> None:
            self.send_response(status)
            self.send_header("Location", location)
            for k, v in extra_headers or []:
                self.send_header(k, v)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path == "/api/ground-truth":
                self._send_json(ground_truth_matches())
                return

            if path == "/api/books":
                self._send_json({"layout": layout, "books": [asdict(b) for b in CATALOG]})
                return

            if path == "/":
                self._redirect("/catalog" if self._is_authenticated() else "/login")
                return

            if path == "/login":
                self._send_html(_render_login())
                return

            if not self._is_authenticated():
                self._redirect("/login")
                return

            if path == "/catalog":
                if layout == "v1":
                    category = qs.get("category", ["All"])[0]
                    max_price = qs.get("max_price", [""])[0]
                    page = int(qs.get("page", ["1"])[0])
                    self._send_html(_render_catalog_v1(category, max_price, page))
                else:
                    topic = qs.get("topic", ["All"])[0]
                    price_cap = qs.get("price_cap", [""])[0]
                    page = int(qs.get("p", ["1"])[0])
                    self._send_html(_render_catalog_v2(topic, price_cap, page))
                return

            if path.startswith("/book/"):
                try:
                    book_id = int(path.removeprefix("/book/"))
                except ValueError:
                    self._send_html(_page_shell("Not Found", "<h1>Invalid book ID</h1>"), status=404)
                    return
                book = BOOK_BY_ID.get(book_id)
                if book is None:
                    self._send_html(_page_shell("Not Found", "<h1>Book not found</h1>"), status=404)
                    return
                rendered = _render_detail_v1(book) if layout == "v1" else _render_detail_v2(book)
                self._send_html(rendered)
                return

            self._send_html(_page_shell("Not Found", "<h1>404 Not Found</h1>"), status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/login":
                self._send_html(_page_shell("Not Found", "<h1>404</h1>"), status=404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            form = parse_qs(raw_body)
            email = form.get("email", [""])[0].strip()
            password = form.get("password", [""])[0]
            if email == DEMO_EMAIL and password == DEMO_PASSWORD:
                cookie_header = f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/; HttpOnly; SameSite=Lax"
                self._redirect("/catalog", status=303, extra_headers=[("Set-Cookie", cookie_header)])
            else:
                self._send_html(_render_login("Invalid email or password."), status=401)

    return DevBooksHandler


class DevBooksServer:
    """Context manager running DevBooks Catalog on a background thread."""

    def __init__(self, layout: str = "v1", host: str = "127.0.0.1", port: int = 0) -> None:
        if layout not in ("v1", "v2"):
            raise ValueError(f"Unsupported layout: {layout}")
        self.layout = layout
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._httpd is not None
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> DevBooksServer:
        self._httpd = ThreadingHTTPServer((self.host, self.port), make_handler(self.layout))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local DevBooks Catalog server.")
    parser.add_argument("--layout", choices=["v1", "v2"], default="v1")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(args.layout))
    print(f"DevBooks Catalog ({args.layout}) listening on http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
