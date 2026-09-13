"""Normalization, hashing, and placeholder fingerprints for prompt candidates."""

from __future__ import annotations

import hashlib
import re

_PLACEHOLDER = re.compile(
    r"\$\{[^}]+\}|\{[a-zA-Z_][a-zA-Z0-9_]*\}|<[^>]+>|\[YOUR_[A-Z0-9_]+\]"
)
_WHITESPACE = re.compile(r"\s+")


def sha256_text(text: str) -> str:
    """Return hex SHA-256 of UTF-8 ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace and strip."""
    lines = [_WHITESPACE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def content_hash(body: str) -> str:
    """SHA-256 of whitespace-normalized prompt body."""
    return sha256_text(normalize_whitespace(body))


def placeholder_fingerprint(body: str) -> str:
    """SHA-256 after replacing placeholders with a stable token."""
    replaced = _PLACEHOLDER.sub("{VAR}", body)
    return sha256_text(normalize_whitespace(replaced).lower())


def normalize_title(title: str) -> str:
    """Lowercase title for duplicate-name comparison."""
    return _WHITESPACE.sub(" ", title).strip().lower()
