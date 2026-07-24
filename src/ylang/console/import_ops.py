"""Shared JSON import logic for console and CLI."""

from __future__ import annotations

from ylang.core.memory import MemoryStore
from ylang.library.store import Library


from ylang.library.types import TemplateParam, TemplateVisibility


def import_json_payload(
    library: Library,
    memory: MemoryStore,
    payload: dict[str, object],
) -> tuple[int, int]:
    """Import templates and facts from an export payload. Returns (templates, facts) counts."""
    imported_templates = 0
    for item in payload.get("templates", []):
        if not isinstance(item, dict):
            continue
        params = [
            TemplateParam(
                name=str(p["name"]),
                description=str(p.get("description", "")),
                default=p.get("default"),
            )
            for p in item.get("params", [])
            if isinstance(p, dict)
        ]
        visibility: TemplateVisibility = item.get("visibility")  # type: ignore[assignment]
        if visibility not in {"public", "private", "archived"}:
            visibility = "private"
        source = str(item.get("source", "user"))
        if source not in {"seed", "user", "learned"}:
            source = "user"
        if source == "learned":
            from ylang.library.store import save_learned_template

            save_learned_template(
                library,
                str(item["template_id"]),
                name=str(item["name"]),
                body=str(item["body"]),
                params=params,
            )
        else:
            library.save(
                str(item["template_id"]),
                name=str(item["name"]),
                body=str(item["body"]),
                params=params,
                source=source,  # type: ignore[arg-type]
                visibility=visibility,
                tags=list(item.get("tags", [])) if isinstance(item.get("tags"), list) else [],
            )
        imported_templates += 1
    imported_facts = 0
    for item in payload.get("facts", []):
        if not isinstance(item, dict):
            continue
        memory.remember(
            str(item["fact"]),
            str(item.get("scope", "private")),
            workspace=str(item.get("workspace", "")),
        )
        imported_facts += 1
    return imported_templates, imported_facts
