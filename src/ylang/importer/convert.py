"""Convert external prompt records into library template fields."""

from __future__ import annotations

import csv
import io
import re
from typing import TYPE_CHECKING

from ylang.importer.types import ParsedPrompt
from ylang.library.types import TemplateParam

if TYPE_CHECKING:
    from collections.abc import Iterable

_DOLLAR_VAR = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")
_BRACE_PARAM = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Build a filesystem-safe template_id slug from a display name."""
    slug = _NON_SLUG.sub("-", text.lower().strip())
    slug = slug.strip("-")
    return slug or "prompt"


def _param_name(raw: str) -> str:
    """Normalize a placeholder label into a valid format key."""
    cleaned = raw.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = cleaned.strip("_")
    return cleaned or "param"


def normalize_body(body: str) -> tuple[str, list[TemplateParam]]:
    """Extract params from body; use {input} when none are declared."""
    params: dict[str, TemplateParam] = {}

    def replace_dollar(match: re.Match[str]) -> str:
        name = _param_name(match.group(1))
        default = match.group(2)
        if name not in params:
            params[name] = TemplateParam(
                name=name,
                description=f"Value for {match.group(1).strip()}",
                default=default,
            )
        return "{" + name + "}"

    normalized = _DOLLAR_VAR.sub(replace_dollar, body)
    for match in _BRACE_PARAM.finditer(normalized):
        name = match.group(1)
        if name not in params:
            params[name] = TemplateParam(
                name=name,
                description=f"Template parameter {name}",
            )
    if not params:
        params["input"] = TemplateParam(
            name="input",
            description="Additional user context",
            default="",
        )
    return normalized, list(params.values())


def parse_csv_rows(csv_text: str) -> list[tuple[str, str]]:
    """Parse awesome-chatgpt-prompts CSV into (act, prompt) pairs."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None or "act" not in reader.fieldnames or "prompt" not in reader.fieldnames:
        msg = "CSV must include act and prompt columns"
        raise ValueError(msg)
    rows: list[tuple[str, str]] = []
    for row in reader:
        act = (row.get("act") or "").strip()
        prompt = (row.get("prompt") or "").strip()
        if act and prompt:
            rows.append((act, prompt))
    return rows


def convert_rows(rows: Iterable[tuple[str, str]]) -> list[ParsedPrompt]:
    """Map external rows to ParsedPrompt values with unique template_ids."""
    seen_ids: set[str] = set()
    parsed: list[ParsedPrompt] = []
    for act, prompt in rows:
        base_id = slugify(act)
        template_id = base_id
        if template_id in seen_ids:
            suffix = 2
            while f"{base_id}-{suffix}" in seen_ids:
                suffix += 1
            template_id = f"{base_id}-{suffix}"
        seen_ids.add(template_id)
        body, params = normalize_body(prompt)
        parsed.append(
            ParsedPrompt(
                template_id=template_id,
                name=act,
                body=body,
                params=params,
            )
        )
    return parsed
