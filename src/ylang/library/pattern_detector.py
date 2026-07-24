"""Usage-based pattern detection for learned template proposals."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from typing import TYPE_CHECKING

from ylang.library.patterns import (
    DetectedPattern,
    PatternDetector,
    PatternProposalOutcome,
    TemplateProposal,
)
from ylang.library.types import TemplateParam
from ylang.usage.store import UsageStore, UsageWindow

if TYPE_CHECKING:
    from ylang.core.engine import Engine

logger = logging.getLogger(__name__)

_MIN_OCCURRENCES = 3
_IMPROVE_ACTIVITY_PREFIX = "improve:"
_SIMILARITY_THRESHOLD = 0.85

_TEMPLATE_SYNTHESIS_SYSTEM = """\
You synthesize reusable prompt templates from repeated user prompt patterns.
Respond with JSON only: {"body": "...", "param_names": ["name1"]}
The body should be a template with {param} placeholders for variable parts.
Keep the template general enough to cover the cluster but faithful to the pattern.
"""


def synthesize_template_from_pattern(
    pattern: DetectedPattern,
    engine: Engine,
    *,
    model: str | None = None,
) -> str | None:
    """Use the engine to synthesize a real template body from a detected pattern."""
    completion = engine.complete(
        [
            {"role": "system", "content": _TEMPLATE_SYNTHESIS_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Pattern id: {pattern.pattern_id}\n"
                    f"Occurrences: {pattern.occurrence_count}\n"
                    f"Sample text:\n{pattern.sample_text}"
                ),
            },
        ],
        activity="improve:agent",
        model=model,
        response_format={"type": "json_object"},
        improver_fired=False,
    )
    if not completion.success:
        logger.debug("template synthesis LLM failed: %s", completion.error)
        return None
    try:
        payload = json.loads(completion.content)
        body = str(payload.get("body", "")).strip()
        return body or None
    except (json.JSONDecodeError, TypeError):
        logger.debug("template synthesis parse failed", exc_info=True)
        return None


class UsagePatternDetector(PatternDetector):
    """Detect repeated improver input texts from usage history."""

    def __init__(self, store: UsageStore) -> None:
        self._store = store

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        """Return prompt patterns seen at least three times in improver usage rows."""
        window = UsageWindow.last_days(window_days)
        rows = self._store.recall_usage(window)
        texts: list[str] = []
        for row in rows:
            if not row.improver_fired:
                continue
            if not row.activity.startswith(_IMPROVE_ACTIVITY_PREFIX):
                continue
            sample = row.improver_input_sample
            if sample:
                if is_trivial_prompt_pattern(sample):
                    continue
                normalized = normalize_prompt_text(sample)
                if normalized:
                    texts.append(sample)
        clusters = cluster_prompt_texts(texts)
        patterns: list[DetectedPattern] = []
        for cluster in clusters:
            if len(cluster) < _MIN_OCCURRENCES:
                continue
            representative = cluster[0]
            pattern_id = pattern_id_from_text(representative)
            patterns.append(
                DetectedPattern(
                    pattern_id=pattern_id,
                    sample_text=representative,
                    occurrence_count=len(cluster),
                )
            )
        return sorted(patterns, key=lambda item: item.occurrence_count, reverse=True)


_TRIVIAL_PROMPT_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(fix|update|continue|go|yes|no|ok|thanks?)\.?$", re.I),
    re.compile(r"^(hi|hello|hey)\.?$", re.I),
    re.compile(r"^(test|testing)\.?$", re.I),
    re.compile(r"^what\s+next\??$", re.I),
    re.compile(r"^(commit(\s+and\s+push)?|push(\s+changes)?|ship(\s+it)?)\.?$", re.I),
    re.compile(r"^(next|proceed|do\s+it|keep\s+going|go\s+ahead)\.?$", re.I),
)

_MIN_LEARNED_BODY_LENGTH = 40
_MIN_WRAPPER_CHARS = 30
_REWRITE_SIMILARITY_THRESHOLD = 0.85
_PASSTHROUGH_PARAM_NAMES = frozenset({"sample", "prompt", "text", "input", "query"})
_STRUCTURAL_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def is_trivial_prompt_pattern(text: str) -> bool:
    """Return True for underspecified prompts that should not become learned templates."""
    normalized = normalize_prompt_text(text)
    if len(normalized) < 4:
        return True
    if any(pattern.search(normalized) for pattern in _TRIVIAL_PROMPT_RES):
        return True
    if len(normalized) < _MIN_LEARNED_BODY_LENGTH and len(normalized.split()) <= 4:
        return True
    return False


def has_structural_placeholders(body: str) -> bool:
    """Return True when body contains at least one ``{param}`` placeholder."""
    return bool(_STRUCTURAL_PLACEHOLDER_RE.search(body))


def is_substantial_rewrite(body: str, sample_text: str) -> bool:
    """Return True when body differs meaningfully from the source prompt."""
    normalized_body = normalize_prompt_text(body)
    normalized_sample = normalize_prompt_text(sample_text)
    if normalized_body == normalized_sample:
        return False
    ratio = difflib.SequenceMatcher(None, normalized_body, normalized_sample).ratio()
    return ratio < _REWRITE_SIMILARITY_THRESHOLD


def _non_placeholder_content(body: str) -> str:
    return normalize_prompt_text(_STRUCTURAL_PLACEHOLDER_RE.sub(" ", body))


def is_passthrough_copy(
    body: str,
    params: list[TemplateParam],
    sample_text: str,
) -> bool:
    """Return True when params only echo the detected prompt without reusable structure."""
    normalized_sample = normalize_prompt_text(sample_text)
    for param in params:
        if param.name.lower() not in _PASSTHROUGH_PARAM_NAMES:
            continue
        default = param.default or ""
        normalized_default = normalize_prompt_text(default)
        if not normalized_default:
            continue
        if normalized_default == normalized_sample:
            return True
        ratio = difflib.SequenceMatcher(None, normalized_default, normalized_sample).ratio()
        if ratio >= 0.9:
            return True
    if not has_structural_placeholders(body):
        return False
    wrapper = _non_placeholder_content(body)
    if len(wrapper) < _MIN_WRAPPER_CHARS and normalized_sample in wrapper + normalized_sample:
        try:
            values = {param.name: param.default or "" for param in params}
            rendered = normalize_prompt_text(body.format(**values))
        except KeyError:
            return True
        if normalized_sample in rendered:
            extra = rendered.replace(normalized_sample, "", 1).strip()
            if len(extra) < _MIN_WRAPPER_CHARS:
                return True
    return False


def evaluate_learned_template_quality(
    body: str,
    *,
    sample_text: str | None = None,
    params: list[TemplateParam] | None = None,
) -> tuple[bool, str | None]:
    """Validate a learned-template body before proposal or persistence."""
    stripped = body.strip()
    if sample_text and is_trivial_prompt_pattern(sample_text):
        return False, "source prompt is trivial or underspecified"
    if len(stripped) < _MIN_LEARNED_BODY_LENGTH:
        return (
            False,
            f"body too short ({len(stripped)} chars, minimum {_MIN_LEARNED_BODY_LENGTH})",
        )
    if params and sample_text and is_passthrough_copy(stripped, params, sample_text):
        return (
            False,
            "body only wraps the source prompt without reusable structure",
        )
    if not has_structural_placeholders(stripped):
        if sample_text and not is_substantial_rewrite(stripped, sample_text):
            return (
                False,
                "body has no {param} placeholders and closely matches the source prompt",
            )
        return False, "body has no {param} placeholders"
    if sample_text and not is_substantial_rewrite(stripped, sample_text):
        wrapper = _non_placeholder_content(stripped)
        if len(wrapper) < _MIN_WRAPPER_CHARS:
            return (
                False,
                "body closely matches the source prompt without a substantial rewrite",
            )
    return True, None


def normalize_prompt_text(text: str) -> str:
    """Lowercase and collapse whitespace for prompt similarity grouping."""
    return " ".join(text.lower().split())


def pattern_id_from_text(text: str) -> str:
    """Stable slug id from normalized prompt prefix."""
    normalized = normalize_prompt_text(text)
    prefix = normalized[:80]
    slug = re.sub(r"[^a-z0-9]+", "-", prefix).strip("-")
    if len(slug) >= 8:
        return slug[:48]
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:12]
    return f"prompt-{digest}"


def cluster_prompt_texts(texts: list[str]) -> list[list[str]]:
    """Group similar prompt texts using normalized difflib ratio."""
    clusters: list[list[str]] = []
    for text in texts:
        normalized = normalize_prompt_text(text)
        if not normalized:
            continue
        matched = False
        for cluster in clusters:
            representative = normalize_prompt_text(cluster[0])
            ratio = difflib.SequenceMatcher(None, normalized, representative).ratio()
            if ratio >= _SIMILARITY_THRESHOLD:
                cluster.append(text)
                matched = True
                break
        if not matched:
            clusters.append([text])
    return clusters


def propose_template_from_pattern(
    pattern: DetectedPattern,
    *,
    engine: Engine | None = None,
) -> TemplateProposal | None:
    """Convert a detected pattern into a propose-only learned template.

    When ``engine`` is provided, synthesizes a real template body via LLM instead
    of the placeholder stub.
    """
    return propose_template_from_pattern_outcome(pattern, engine=engine).proposal


def propose_template_from_pattern_outcome(
    pattern: DetectedPattern,
    *,
    engine: Engine | None = None,
) -> PatternProposalOutcome:
    """Convert a detected pattern into a proposal outcome with quality gate metadata."""
    if pattern.occurrence_count < _MIN_OCCURRENCES:
        return PatternProposalOutcome(
            proposal=None,
            skip_reason="pattern has fewer than three occurrences",
        )
    if is_trivial_prompt_pattern(pattern.sample_text):
        return PatternProposalOutcome(
            proposal=None,
            skip_reason="source prompt is trivial or underspecified",
        )
    template_id = f"learned-{pattern.pattern_id}"
    preview = pattern.sample_text[:120].replace("\n", " ")
    body = "Reuse the prompt pattern detected from your improver history:\n\n{sample}"
    params = [
        TemplateParam(
            name="sample",
            description="Example text from detected pattern",
            default=pattern.sample_text,
        )
    ]
    if engine is not None:
        synthesized = synthesize_template_from_pattern(pattern, engine)
        if synthesized:
            body = synthesized
            params = [
                TemplateParam(
                    name="task",
                    description="Task-specific detail for this template",
                    default=pattern.sample_text[:200],
                )
            ]
    ok, skip_reason = evaluate_learned_template_quality(
        body,
        sample_text=pattern.sample_text,
        params=params,
    )
    if not ok:
        return PatternProposalOutcome(proposal=None, skip_reason=skip_reason)
    return PatternProposalOutcome(
        proposal=TemplateProposal(
            suggested_template_id=template_id,
            name=f"Learned: {pattern.pattern_id.replace('-', ' ').title()}",
            body=body,
            params=params,
            rationale=(
                f"Detected {pattern.occurrence_count} similar improver prompts "
                f'(e.g. "{preview}") in the last 30 days.'
            ),
        )
    )
