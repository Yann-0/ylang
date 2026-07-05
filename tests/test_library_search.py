"""FTS template search tests."""

from __future__ import annotations

from ylang.core.stores import open_stores


def test_library_search_finds_template(db_path) -> None:
    stores = open_stores(db_path)
    stores.library.save(
        "feature-spec",
        name="Feature specification",
        body="Write acceptance criteria and test plan",
        params=[],
        source="user",
        tags=["feature", "spec"],
    )
    hits = stores.library.search("acceptance criteria")
    assert any(item.template_id == "feature-spec" for item in hits)
    stores.close()
