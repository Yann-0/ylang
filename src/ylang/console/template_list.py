"""Filter, sort, and paginate templates for the admin console list view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from ylang.library.types import TemplateSource, TemplateSummary, TemplateVisibility

SortField = Literal["id", "name", "source", "version", "usage", "updated"]
SortOrder = Literal["asc", "desc"]

_PER_PAGE_OPTIONS = (10, 25, 50, 100)
_DEFAULT_PER_PAGE = 25
_VALID_SORTS: frozenset[str] = frozenset({"id", "name", "source", "version", "usage", "updated"})
_VALID_SOURCES: frozenset[str] = frozenset({"seed", "user", "learned"})


_VALID_VISIBILITIES: frozenset[str] = frozenset(
    {"public", "private", "archived", "all"}
)


@dataclass(frozen=True, slots=True)
class TemplateListFilters:
    """Query parameters for the template browser list."""

    query: str = ""
    source: TemplateSource | None = None
    visibility: TemplateVisibility | Literal["all"] | None = None
    unused_only: bool = False
    toxic_only: bool = False
    sort: SortField = "name"
    order: SortOrder = "asc"
    page: int = 1
    per_page: int = _DEFAULT_PER_PAGE


@dataclass(frozen=True, slots=True)
class TemplateListRow:
    """One template row with improver injection usage."""

    summary: TemplateSummary
    usage_count: int


@dataclass(frozen=True, slots=True)
class TemplateListPage:
    """Paginated template list result."""

    rows: tuple[TemplateListRow, ...]
    total: int
    page: int
    per_page: int
    filters: TemplateListFilters

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


def parse_template_list_filters(
    params: dict[str, str],
    *,
    default_per_page: int = _DEFAULT_PER_PAGE,
) -> TemplateListFilters:
    """Parse and validate template list query parameters."""
    query = params.get("q", "").strip()
    source_raw = params.get("source", "").strip().lower()
    source: TemplateSource | None = None
    if source_raw and source_raw in _VALID_SOURCES:
        source = source_raw  # type: ignore[assignment]

    unused_raw = params.get("unused", "").strip().lower()
    unused_only = unused_raw in {"1", "true", "yes", "on"}

    toxic_raw = params.get("toxic", "").strip().lower()
    toxic_only = toxic_raw in {"1", "true", "yes", "on"}

    visibility_raw = params.get("visibility", "").strip().lower()
    visibility: TemplateVisibility | Literal["all"] | None = None
    if visibility_raw in _VALID_VISIBILITIES:
        visibility = visibility_raw  # type: ignore[assignment]

    sort_raw = params.get("sort", "name").strip().lower()
    sort: SortField = sort_raw if sort_raw in _VALID_SORTS else "name"  # type: ignore[assignment]

    order_raw = params.get("order", "asc").strip().lower()
    order: SortOrder = "desc" if order_raw == "desc" else "asc"

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

    return TemplateListFilters(
        query=query,
        source=source,
        visibility=visibility,
        unused_only=unused_only,
        toxic_only=toxic_only,
        sort=sort,
        order=order,
        page=page,
        per_page=per_page,
    )


def filter_and_paginate_templates(
    templates: list[TemplateSummary],
    *,
    filters: TemplateListFilters,
    usage_counts: dict[str, int],
    toxic_ids: frozenset[str] | set[str] | None = None,
) -> TemplateListPage:
    """Apply source/unused/toxic filters, sort, and pagination to template summaries."""
    filtered = list(templates)
    if filters.source is not None:
        filtered = [item for item in filtered if item.source == filters.source]
    if filters.visibility is not None and filters.visibility != "all":
        filtered = [
            item for item in filtered if item.visibility == filters.visibility
        ]
    if filters.unused_only:
        filtered = [
            item for item in filtered if usage_counts.get(item.template_id, 0) == 0
        ]
    if filters.toxic_only:
        blocked = toxic_ids or frozenset()
        filtered = [item for item in filtered if item.template_id in blocked]

    reverse = filters.order == "desc"

    def sort_key(item: TemplateSummary) -> tuple[object, ...]:
        if filters.sort == "usage":
            return (usage_counts.get(item.template_id, 0), item.name.lower())
        if filters.sort == "version":
            return (item.latest_version, item.template_id)
        if filters.sort == "updated":
            return (item.updated_at.timestamp(), item.template_id)
        if filters.sort == "source":
            return (item.source, item.name.lower())
        if filters.sort == "id":
            return (item.template_id.lower(),)
        return (item.name.lower(), item.template_id)

    filtered.sort(key=sort_key, reverse=reverse)
    total = len(filtered)
    total_pages = max(1, (total + filters.per_page - 1) // filters.per_page) if total else 1
    page = min(filters.page, total_pages) if total else 1
    start = (page - 1) * filters.per_page
    end = start + filters.per_page
    page_items = filtered[start:end]

    rows = tuple(
        TemplateListRow(
            summary=item,
            usage_count=usage_counts.get(item.template_id, 0),
        )
        for item in page_items
    )
    return TemplateListPage(
        rows=rows,
        total=total,
        page=page,
        per_page=filters.per_page,
        filters=TemplateListFilters(
            query=filters.query,
            source=filters.source,
            visibility=filters.visibility,
            unused_only=filters.unused_only,
            toxic_only=filters.toxic_only,
            sort=filters.sort,
            order=filters.order,
            page=page,
            per_page=filters.per_page,
        ),
    )


def build_template_list_query(
    filters: TemplateListFilters,
    *,
    template_id: str | None = None,
    message: str | None = None,
) -> str:
    """Build a query string preserving list filters and optional selection."""
    params: dict[str, str] = {}
    if filters.query:
        params["q"] = filters.query
    if filters.source is not None:
        params["source"] = filters.source
    if filters.visibility is not None:
        params["visibility"] = filters.visibility
    if filters.unused_only:
        params["unused"] = "1"
    if filters.toxic_only:
        params["toxic"] = "1"
    if filters.sort != "name":
        params["sort"] = filters.sort
    if filters.order != "asc":
        params["order"] = filters.order
    if filters.page > 1:
        params["page"] = str(filters.page)
    if filters.per_page != _DEFAULT_PER_PAGE:
        params["per_page"] = str(filters.per_page)
    if template_id:
        params["id"] = template_id
    if message:
        params["msg"] = message
    return urlencode(params)
