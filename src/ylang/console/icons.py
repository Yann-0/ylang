"""Inline SVG icons for console action buttons (offline-friendly)."""

from __future__ import annotations

from html import escape


def _svg(path_d: str, *, label: str, size: int = 16) -> str:
    """Return an accessible inline SVG icon."""
    return (
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'aria-label="{escape(label)}" role="img" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">'
        f"{path_d}</svg>"
    )


def icon_edit(*, size: int = 16) -> str:
    """Pencil icon for edit actions."""
    return _svg(
        '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
        label="Edit",
        size=size,
    )


def icon_delete(*, size: int = 16) -> str:
    """Trash icon for delete actions."""
    return _svg(
        '<path d="M3 6h18"/><path d="M8 6V4h8v2"/>'
        '<path d="M19 6v14H5V6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
        label="Delete",
        size=size,
    )


def icon_view(*, size: int = 16) -> str:
    """Eye icon for view/open actions."""
    return _svg(
        '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/>'
        '<circle cx="12" cy="12" r="3"/>',
        label="View",
        size=size,
    )
