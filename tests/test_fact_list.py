"""Tests for facts list filtering and pagination."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ylang.console.fact_list import (
    filter_and_paginate_facts,
    parse_fact_list_filters,
)
from ylang.core.memory import Fact


def _fact(
    fact_id: int,
    text: str,
    *,
    scope: str = "private",
    workspace: str = "",
    hours_ago: int = 0,
) -> Fact:
    return Fact(
        id=fact_id,
        fact=text,
        scope=scope,  # type: ignore[arg-type]
        created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        workspace=workspace,
    )


def test_parse_fact_list_filters_defaults() -> None:
    filters = parse_fact_list_filters({})
    assert filters.page == 1
    assert filters.per_page == 25
    assert filters.sort == "created"
    assert filters.order == "desc"
    assert filters.scope is None


def test_parse_fact_list_filters_ignores_invalid_scope() -> None:
    filters = parse_fact_list_filters({"scope": "bogus"})
    assert filters.scope is None


def test_filter_and_paginate_by_scope_and_query() -> None:
    facts = [
        _fact(1, "Prefer Vitest", scope="private", workspace="ylang"),
        _fact(2, "Use Postgres", scope="shareable", workspace="api"),
        _fact(3, "Prefer dark mode", scope="private", workspace="ui"),
    ]
    filters = parse_fact_list_filters(
        {"scope": "private", "q": "prefer", "per_page": "10"}
    )
    page = filter_and_paginate_facts(facts, filters=filters)
    assert page.total == 2
    assert {row.id for row in page.rows} == {1, 3}


def test_filter_and_paginate_pages() -> None:
    facts = [_fact(index, f"fact-{index:02d}", hours_ago=index) for index in range(15)]
    filters = parse_fact_list_filters({"per_page": "10", "page": "2", "order": "asc"})
    page = filter_and_paginate_facts(facts, filters=filters)
    assert page.total == 15
    assert page.page == 2
    assert len(page.rows) == 5
    assert page.start_index == 11
