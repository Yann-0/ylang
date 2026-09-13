"""Import public prompt collections into the Ylang candidate quarantine."""

from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING

from ylang.importer.adapters.prompts_chat import PROMPTS_CHAT_CSV_NAME, PromptsChatAdapter
from ylang.importer.convert import convert_rows, parse_csv_rows
from ylang.importer.fetch import DEFAULT_PROMPTS_URL, load_csv_text
from ylang.importer.ingest import ingest_parsed_items
from ylang.importer.refresh import open_source_store, refresh_source
from ylang.importer.source_types import MANUAL_SOURCE_ID
from ylang.importer.types import ImportResult, ParsedPrompt
from ylang.library import open_library

if TYPE_CHECKING:
    from ylang.library.store import Library

__all__ = [
    "DEFAULT_PROMPTS_URL",
    "ImportResult",
    "ParsedPrompt",
    "convert_rows",
    "import_into_library",
    "import_prompts",
    "load_csv_text",
    "parse_csv_rows",
]


def _result_from_summary(summary: object) -> ImportResult:
    imported = int(getattr(summary, "imported", 0))
    skipped = int(getattr(summary, "skipped", 0))
    error = getattr(summary, "error", None)
    status = getattr(summary, "status", "success")
    return ImportResult(
        imported=imported,
        skipped=skipped,
        new=int(getattr(summary, "new", imported)),
        changed=int(getattr(summary, "changed", 0)),
        quarantined=int(getattr(summary, "quarantined", 0)),
        source_id=str(getattr(summary, "source_id", "")),
        error=str(error) if error else None,
        ok=status in {"success", "unchanged"},
    )


def import_prompts(
    library: Library,
    *,
    url: str | None = None,
    csv_path: Path | None = None,
    csv_text: str | None = None,
) -> ImportResult:
    """Import external prompts as **candidates**, not active templates.

    Internet content is quarantined until explicit human promotion.
    An arbitrary ``url`` is never registered as a scheduled source.
    """
    store = open_source_store(library)
    if csv_text is None and csv_path is None and url is None:
        summary = refresh_source(store, library, "prompts-chat")
        return _result_from_summary(summary)
    if csv_text is None:
        csv_text = load_csv_text(url=url, csv_path=csv_path)
    items = PromptsChatAdapter().parse(
        {PROMPTS_CHAT_CSV_NAME: csv_text},
        revision="sha256:local-csv",
    )
    source_id = "prompts-chat"
    if url and url != DEFAULT_PROMPTS_URL and csv_path is None:
        source_id = MANUAL_SOURCE_ID
    source = store.get_source(source_id)
    if source is None:
        return ImportResult(imported=0, skipped=0, ok=False, error="source missing")
    summary = ingest_parsed_items(
        store,
        library,
        source,
        items,
        revision="sha256:local-csv",
        mark_removed=False,
    )
    store.record_run(summary)
    return _result_from_summary(summary)


def import_into_library(
    db_path: Path,
    *,
    url: str | None = None,
    csv_path: Path | None = None,
    csv_text: str | None = None,
) -> ImportResult:
    """Open ``db_path``, import candidates, then close the library connection."""
    library = open_library(db_path)
    try:
        return import_prompts(
            library,
            url=url,
            csv_path=csv_path,
            csv_text=csv_text,
        )
    finally:
        library.close()
