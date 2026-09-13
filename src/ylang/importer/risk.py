"""Static prompt-risk scanning. Triage only — never a safety proof."""

from __future__ import annotations

import re

from ylang.importer.source_types import RiskReport

_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "high",
        "reveal_secrets",
        re.compile(
            r"(reveal|print|dump|exfiltrate|show).{0,40}(api[_ -]?key|secret|password|"
            r"credential|\.env|access token)|read.{0,20}(api[_ -]?key|env(ironment)? vars?)",
            re.I,
        ),
    ),
    (
        "high",
        "exfiltrate_files",
        re.compile(
            r"(upload|exfiltrate|send|post).{0,40}(file|home directory|/etc/passwd|"
            r"id_rsa|\.ssh)|curl\s+\S+\s+\|\s*(ba)?sh",
            re.I,
        ),
    ),
    (
        "high",
        "ignore_higher_priority",
        re.compile(
            r"ignore (all )?(previous|prior|above|system|developer) (instructions|policies)|"
            r"disregard (your )?(safety|guardrails|system prompt)",
            re.I,
        ),
    ),
    (
        "high",
        "disable_safety",
        re.compile(
            r"jailbreak|disable (safety|filters?|guardrails)|no restrictions|"
            r"without (any )?(safety |ethical )?filter",
            re.I,
        ),
    ),
    (
        "high",
        "destructive_shell",
        re.compile(
            r"rm\s+-rf\s+|mkfs\.|dd\s+if=|:\(\)\s*\{\s*:\|:&",
            re.I,
        ),
    ),
    (
        "high",
        "force_push_or_reset",
        re.compile(
            r"git\s+push\s+.*--force|git\s+reset\s+--hard|git\s+checkout\s+--theirs|"
            r"git\s+push\s+-f\b",
            re.I,
        ),
    ),
    (
        "high",
        "install_remote_code",
        re.compile(
            r"(curl|wget).{0,80}\|\s*(sudo\s+)?(ba)?sh|pip install\s+[^\s]+://|"
            r"npx\s+--yes|eval\s*\(|Invoke-Expression",
            re.I,
        ),
    ),
    (
        "high",
        "auto_execute_transactions",
        re.compile(
            r"without (user )?confirmation.{0,40}(send|pay|transfer|commit|push)|"
            r"automatically (send|pay|transfer|wire) (the )?(money|funds|message|email)",
            re.I,
        ),
    ),
    (
        "review",
        "broad_tools",
        re.compile(
            r"\b(all tools|every tool|unrestricted tools|full (system )?access|"
            r"enable all mcp)\b",
            re.I,
        ),
    ),
    (
        "review",
        "obfuscated_instructions",
        re.compile(
            r"base64.{0,20}(decode|decode and (run|exec))|\u200b|&#x[0-9a-f]+;",
            re.I,
        ),
    ),
)


def scan_prompt_risk(body: str, *, metadata_tools: object = None) -> RiskReport:
    """Return risk_level and reason codes for candidate prompt text.

    Static scanning is triage. Absence of flags is not ``SAFE = true``.
    """
    reasons: list[str] = []
    level: str = "low"
    for rule_level, code, pattern in _RULES:
        if pattern.search(body):
            reasons.append(code)
            if rule_level == "high":
                level = "high"
            elif level != "high":
                level = "review"
    if metadata_tools:
        tools = metadata_tools
        if isinstance(tools, str):
            tools = [tools]
        if isinstance(tools, (list, tuple)) and len(tools) >= 4:
            reasons.append("broad_tools")
            if level == "low":
                level = "review"
    return RiskReport(level=level, reasons=tuple(dict.fromkeys(reasons)))  # type: ignore[arg-type]
