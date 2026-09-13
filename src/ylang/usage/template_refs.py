"""Encode and parse versioned template injection refs for usage rows.

New improver events store ``id@version`` in ``improver_context_templates``.
Legacy bare ``id`` values remain valid and mean unknown version.
"""

from __future__ import annotations

TemplateRef = tuple[str, int | None]


def format_template_ref(template_id: str, version: int | None) -> str:
    """Format one injection ref; omit ``@version`` when version is unknown."""
    tid = template_id.strip()
    if not tid:
        return ""
    if version is None:
        return tid
    return f"{tid}@{int(version)}"


def format_template_refs(refs: list[TemplateRef] | tuple[TemplateRef, ...]) -> str:
    """Join injection refs as a comma-separated usage column value."""
    parts = [
        format_template_ref(template_id, version)
        for template_id, version in refs
        if template_id.strip()
    ]
    return ",".join(parts)


def parse_template_ref(raw: str) -> TemplateRef:
    """Parse ``id`` or ``id@version``; invalid version suffixes stay unversioned."""
    text = raw.strip()
    if not text:
        return ("", None)
    if "@" not in text:
        return (text, None)
    template_id, _, suffix = text.rpartition("@")
    template_id = template_id.strip()
    suffix = suffix.strip()
    if not template_id:
        return (text, None)
    if not suffix.isdigit():
        return (text, None)
    return (template_id, int(suffix))


def parse_template_refs(raw: str | None) -> list[TemplateRef]:
    """Parse a stored ``improver_context_templates`` value into id/version pairs."""
    if not raw:
        return []
    refs: list[TemplateRef] = []
    for part in raw.split(","):
        template_id, version = parse_template_ref(part)
        if template_id:
            refs.append((template_id, version))
    return refs


def template_ids_from_refs(raw: str | None) -> list[str]:
    """Return bare template ids, stripping any ``@version`` suffix."""
    return [template_id for template_id, _ in parse_template_refs(raw)]
