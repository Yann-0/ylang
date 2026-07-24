"""Tests for template list filtering and pagination."""

from __future__ import annotations

from datetime import datetime, timezone

from ylang.console.template_list import (
    build_template_list_query,
    filter_and_paginate_templates,
    parse_template_list_filters,
)
from ylang.library.types import TemplateSummary


def _summary(
    template_id: str,
    *,
    name: str | None = None,
    source: str = "user",
    version: int = 1,
    visibility: str = "private",
) -> TemplateSummary:
    return TemplateSummary(
        template_id=template_id,
        name=name or template_id,
        latest_version=version,
        source=source,  # type: ignore[arg-type]
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        param_names=(),
        visibility=visibility,  # type: ignore[arg-type]
        tags=(),
    )


def test_parse_template_list_filters_defaults() -> None:
    filters = parse_template_list_filters({})
    assert filters.page == 1
    assert filters.per_page == 25
    assert filters.sort == "name"
    assert filters.source is None
    assert filters.visibility is None
    assert filters.unused_only is False
    assert filters.toxic_only is False


def test_parse_template_list_filters_visibility() -> None:
    filters = parse_template_list_filters({"visibility": "archived"})
    assert filters.visibility == "archived"
    filters_all = parse_template_list_filters({"visibility": "all"})
    assert filters_all.visibility == "all"


def test_filter_and_paginate_by_visibility() -> None:
    templates = [
        _summary("active", visibility="public"),
        _summary("hidden", visibility="archived"),
    ]
    filters = parse_template_list_filters({"visibility": "archived", "per_page": "10"})
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={},
    )
    assert page.total == 1
    assert page.rows[0].summary.template_id == "hidden"


def test_build_template_list_query_preserves_visibility() -> None:
    filters = parse_template_list_filters({"visibility": "archived", "unused": "1"})
    query = build_template_list_query(filters)
    assert "visibility=archived" in query
    assert "unused=1" in query


def test_parse_template_list_filters_unused_only() -> None:
    filters = parse_template_list_filters({"unused": "1"})
    assert filters.unused_only is True
    filters_off = parse_template_list_filters({"unused": "0"})
    assert filters_off.unused_only is False


def test_parse_template_list_filters_toxic_only() -> None:
    filters = parse_template_list_filters({"toxic": "1"})
    assert filters.toxic_only is True
    filters_off = parse_template_list_filters({"toxic": "0"})
    assert filters_off.toxic_only is False


def test_filter_and_paginate_toxic_only() -> None:
    templates = [_summary("toxic-a"), _summary("ok-b"), _summary("toxic-c")]
    filters = parse_template_list_filters({"toxic": "1", "per_page": "10"})
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={},
        toxic_ids={"toxic-a", "toxic-c"},
    )
    assert page.total == 2
    assert {row.summary.template_id for row in page.rows} == {"toxic-a", "toxic-c"}
    assert page.filters.toxic_only is True


def test_build_template_list_query_preserves_toxic() -> None:
    filters = parse_template_list_filters({"toxic": "1", "unused": "1"})
    query = build_template_list_query(filters)
    assert "toxic=1" in query
    assert "unused=1" in query


def test_parse_template_list_filters_invalid_page_size() -> None:
    filters = parse_template_list_filters({"per_page": "999", "page": "0"})
    assert filters.per_page == 25
    assert filters.page == 1


def test_filter_and_paginate_by_source() -> None:
    templates = [
        _summary("a", source="user"),
        _summary("b", source="seed"),
        _summary("c", source="learned"),
    ]
    filters = parse_template_list_filters({"source": "user", "per_page": "10"})
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={},
    )
    assert page.total == 1
    assert page.rows[0].summary.template_id == "a"


def test_filter_and_paginate_unused_only() -> None:
    templates = [_summary("used"), _summary("idle"), _summary("also-idle")]
    filters = parse_template_list_filters({"unused": "true", "per_page": "10"})
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={"used": 3, "idle": 0},
    )
    assert page.total == 2
    assert {row.summary.template_id for row in page.rows} == {"idle", "also-idle"}
    assert all(row.usage_count == 0 for row in page.rows)


def test_build_template_list_query_preserves_unused() -> None:
    filters = parse_template_list_filters({"unused": "1", "source": "learned", "page": "2"})
    query = build_template_list_query(filters, template_id="demo")
    assert "unused=1" in query
    assert "source=learned" in query
    assert "page=2" in query
    assert "id=demo" in query


def test_filter_and_paginate_sort_by_usage_desc() -> None:
    templates = [_summary("low"), _summary("high"), _summary("mid")]
    filters = parse_template_list_filters(
        {"sort": "usage", "order": "desc", "per_page": "10"}
    )
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={"low": 1, "mid": 5, "high": 10},
    )
    assert [row.summary.template_id for row in page.rows] == ["high", "mid", "low"]


def test_filter_and_paginate_pages() -> None:
    templates = [_summary(f"t-{index:02d}") for index in range(15)]
    filters = parse_template_list_filters({"per_page": "10", "page": "2"})
    page = filter_and_paginate_templates(
        templates,
        filters=filters,
        usage_counts={},
    )
    assert page.total == 15
    assert page.page == 2
    assert len(page.rows) == 5
    assert page.start_index == 11
    assert page.end_index == 15
