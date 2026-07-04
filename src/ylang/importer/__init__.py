"""Import public prompt collections into the Ylang library."""

from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING

from ylang.importer.convert import convert_rows, parse_csv_rows
from ylang.importer.fetch import DEFAULT_PROMPTS_URL, load_csv_text
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


def import_prompts(
    library: Library,
    *,
    url: str | None = None,
    csv_path: Path | None = None,
    csv_text: str | None = None,
) -> ImportResult:
    """Import external prompts as public seed templates; skip existing template_ids."""
    if csv_text is None:
        csv_text = load_csv_text(url=url, csv_path=csv_path)
    rows = parse_csv_rows(csv_text)
    prompts = convert_rows(rows)
    imported = 0
    skipped = 0
    for spec in prompts:
        if library.recall(spec.template_id) is not None:
            skipped += 1
            continue
        library.save(
            spec.template_id,
            name=spec.name,
            body=spec.body,
            params=spec.params,
            source="seed",
        )
        imported += 1
    return ImportResult(imported=imported, skipped=skipped)


def import_into_library(
    db_path: Path,
    *,
    url: str | None = None,
    csv_path: Path | None = None,
    csv_text: str | None = None,
) -> ImportResult:
    """Open ``db_path``, import seed templates, then close the library connection."""
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
