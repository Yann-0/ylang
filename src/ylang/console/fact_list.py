"""Filter, sort, and paginate facts for the admin console list view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from ylang.core.memory import Fact, FactScope

SortField = Literal["id", "fact", "scope", "workspace", "created"]
SortOrder = Literal["asc", "desc"]

_PER_PAGE_OPTIONS = (10, 25, 50, 100)
_DEFAULT_PER_PAGE = 25
_VALID_SORTS: frozenset[str] = frozenset(
    {"id", "fact", "scope", "workspace", "created"}
)
_VALID_SCOPES: frozenset[str] = frozenset({"private", "shareable"})


@dataclass(frozen=True, slots=True)
class FactListFilters:
    """Query parameters for the facts browser list."""

    query: str = ""
    scope: FactScope | None = None
    workspace: str = ""
    sort: SortField = "created"
    order: SortOrder = "desc"
    page: int = 1
    per_page: int = _DEFAULT_PER_PAGE


@dataclass(frozen=True, slots=True)
class FactListPage:
    """Paginated facts list result."""

    rows: tuple[Fact, ...]
    total: int
    page: int
    per_page: int
    filters: FactListFilters

    @property
    def total_pages(self) -> int:
        """Return the number of pages (at least 1)."""
        if self.total <= 0:
            return 1
        return (self.total + self.per_page - 1) // self.per_page

    @property
    def start_index(self) -> int:
        """Return 1-based index of the first row on this page."""
        if self.total <= 0:
            return 0
        return (self.page - 1) * self.per_page + 1

    @property
    def end_index(self) -> int:
        """Return 1-based index of the last row on this page."""
        if self.total <= 0:
            return 0
        return min(self.page * self.per_page, self.total)


def per_page_options() -> tuple[int, ...]:
    """Return allowed page-size choices."""
    return _PER_PAGE_OPTIONS


def parse_fact_list_filters(
    params: dict[str, str],
    *,
    default_per_page: int = _DEFAULT_PER_PAGE,
) -> FactListFilters:
    """Parse and validate facts list query parameters."""
    query = params.get("q", "").strip()
    scope_raw = params.get("scope", "").strip().lower()
    scope: FactScope | None = None
    if scope_raw in _VALID_SCOPES:
        scope = scope_raw  # type: ignore[assignment]

    workspace = params.get("workspace", "").strip()

    sort_raw = params.get("sort", "created").strip().lower()
    sort: SortField = sort_raw if sort_raw in _VALID_SORTS else "created"  # type: ignore[assignment]

    order_raw = params.get("order", "desc").strip().lower()
    order: SortOrder = "asc" if order_raw == "asc" else "desc"

    try:
        page = max(1, int(params.get("page", "1")))
    except ValueError:
        page = 1

    try:
        per_page = int(params.get("per_page", str(default_per_page)))
    except ValueError:
        per_page = default_per_page
    if per_page not in _PER_PAGE_OPTIONS:
        per_page = default_per_page

    return FactListFilters(
        query=query,
        scope=scope,
        workspace=workspace,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )


def filter_and_paginate_facts(
    facts: list[Fact],
    *,
    filters: FactListFilters,
) -> FactListPage:
    """Apply keyword/scope/workspace filters, sort, and pagination."""
    filtered = list(facts)
    if filters.scope is not None:
        filtered = [item for item in filtered if item.scope == filters.scope]
    if filters.workspace:
        needle = filters.workspace.lower()
        filtered = [
            item for item in filtered if needle in item.workspace.lower()
        ]
    if filters.query:
        needle = filters.query.lower()
        filtered = [
            item
            for item in filtered
            if needle in item.fact.lower()
            or needle in item.workspace.lower()
            or needle in item.scope
            or needle in str(item.id)
        ]

    reverse = filters.order == "desc"

    def sort_key(item: Fact) -> tuple[object, ...]:
        if filters.sort == "id":
            return (item.id,)
        if filters.sort == "scope":
            return (item.scope, -item.id)
        if filters.sort == "workspace":
            return (item.workspace.lower(), -item.id)
        if filters.sort == "fact":
            return (item.fact.lower(), -item.id)
        return (item.created_at.timestamp(), item.id)

    filtered.sort(key=sort_key, reverse=reverse)
    total = len(filtered)
    total_pages = (
        max(1, (total + filters.per_page - 1) // filters.per_page) if total else 1
    )
    page = min(filters.page, total_pages) if total else 1
    start = (page - 1) * filters.per_page
    end = start + filters.per_page
    rows = tuple(filtered[start:end])
    return FactListPage(
        rows=rows,
        total=total,
        page=page,
        per_page=filters.per_page,
        filters=FactListFilters(
            query=filters.query,
            scope=filters.scope,
            workspace=filters.workspace,
            sort=filters.sort,
            order=filters.order,
            page=page,
            per_page=filters.per_page,
        ),
    )


def build_fact_list_query(
    filters: FactListFilters,
    *,
    fact_id: int | None = None,
    message: str | None = None,
) -> str:
    """Build a query string preserving list filters and optional selection."""
    params: dict[str, str] = {}
    if filters.query:
        params["q"] = filters.query
    if filters.scope is not None:
        params["scope"] = filters.scope
    if filters.workspace:
        params["workspace"] = filters.workspace
    if filters.sort != "created":
        params["sort"] = filters.sort
    if filters.order != "desc":
        params["order"] = filters.order
    if filters.page > 1:
        params["page"] = str(filters.page)
    if filters.per_page != _DEFAULT_PER_PAGE:
        params["per_page"] = str(filters.per_page)
    if fact_id is not None:
        params["id"] = str(fact_id)
    if message:
        params["msg"] = message
    return urlencode(params)


#: Starter facts offered when the library is empty (opt-in via console action).
SAMPLE_FACTS: tuple[tuple[str, FactScope, str], ...] = (
    (
        "Prefer TypeScript and Vitest for new tests in this workspace.",
        "shareable",
        "ylang",
    ),
    (
        "Keep changes small and scoped to the requested task.",
        "private",
        "",
    ),
    (
        "Never commit secrets, API keys, or .env files.",
        "shareable",
        "",
    ),
)
