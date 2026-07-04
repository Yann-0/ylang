"""Versioned prompt template library with retrieval and pattern learning.

Re-exports store types, pattern detection registry symbols, and ``open_library``.
``Library.list_templates`` caches summaries in memory until the next ``save()``.
"""

from ylang.library.patterns import (
    DetectedPattern,
    PatternDetector,
    TemplateProposal,
    propose_template_from_pattern,
    register_pattern_detector,
)
from ylang.library.store import Library, open_library
from ylang.library.types import Template, TemplateParam, TemplateSource, TemplateSummary

__all__ = [
    "DetectedPattern",
    "Library",
    "PatternDetector",
    "Template",
    "TemplateParam",
    "TemplateProposal",
    "TemplateSource",
    "TemplateSummary",
    "open_library",
    "propose_template_from_pattern",
    "register_pattern_detector",
]
