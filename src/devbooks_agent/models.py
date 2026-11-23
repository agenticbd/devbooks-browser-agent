"""Shared Pydantic schemas and ground-truth validation helpers."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BookMatch(BaseModel):
    title: str
    price_usd: float
    rating: float
    isbn: str
    in_stock: bool


class CatalogReport(BaseModel):
    query_summary: str
    books: list[BookMatch] = Field(default_factory=list)
    total_cost_usd: float


def reports_match_ground_truth(report: CatalogReport | None, expected: dict[str, Any]) -> bool:
    """Return True if a CatalogReport matches ground truth regardless of book ordering."""
    if report is None:
        return False
    expected_books = sorted(expected["books"], key=lambda b: b["title"].lower())
    actual_books = sorted(
        [b.model_dump() for b in report.books],
        key=lambda b: b["title"].lower(),
    )
    if len(actual_books) != len(expected_books):
        return False
    for got, want in zip(actual_books, expected_books):
        if got["title"].strip() != want["title"]:
            return False
        if abs(float(got["price_usd"]) - float(want["price_usd"])) > 0.01:
            return False
        if abs(float(got["rating"]) - float(want["rating"])) > 0.01:
            return False
        if got["isbn"].strip() != want["isbn"]:
            return False
        if bool(got["in_stock"]) != bool(want["in_stock"]):
            return False
    return abs(float(report.total_cost_usd) - float(expected["total_cost_usd"])) <= 0.01
