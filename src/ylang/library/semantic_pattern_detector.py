"""Semantic prompt pattern detection using TF-IDF cosine similarity."""

from __future__ import annotations

import math
import re
from collections import Counter

from ylang.library.pattern_detector import (
    UsagePatternDetector,
    normalize_prompt_text,
    pattern_id_from_text,
)
from ylang.library.patterns import DetectedPattern
from ylang.usage.store import UsageStore, UsageWindow

_IMPROVE_ACTIVITY_PREFIX = "improve:"
_MIN_OCCURRENCES = 3
_SIMILARITY_THRESHOLD = 0.55
_TOKEN_RE = re.compile(r"[a-z0-9']{3,}")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_prompt_text(text))


def _tfidf_vectors(texts: list[str]) -> list[dict[str, float]]:
    """Build sparse TF-IDF vectors for a list of texts."""
    tokenized = [_tokenize(text) for text in texts]
    doc_count = len(tokenized)
    df: Counter[str] = Counter()
    for tokens in tokenized:
        for token in set(tokens):
            df[token] += 1
    vectors: list[dict[str, float]] = []
    for tokens in tokenized:
        tf = Counter(tokens)
        total = len(tokens) or 1
        vector: dict[str, float] = {}
        for token, count in tf.items():
            idf = math.log((doc_count + 1) / (df[token] + 1)) + 1.0
            vector[token] = (count / total) * idf
        vectors.append(vector)
    return vectors


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left.get(key, 0.0) * right.get(key, 0.0) for key in left)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def cluster_prompt_texts_semantic(
    texts: list[str],
    *,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> list[list[str]]:
    """Group semantically similar prompts using TF-IDF cosine similarity."""
    if not texts:
        return []
    vectors = _tfidf_vectors(texts)
    clusters: list[list[str]] = []
    cluster_vectors: list[dict[str, float]] = []
    for text, vector in zip(texts, vectors, strict=True):
        matched = False
        for index, centroid in enumerate(cluster_vectors):
            if _cosine_similarity(vector, centroid) >= threshold:
                clusters[index].append(text)
                # Update centroid as average (simple incremental blend)
                for key, value in vector.items():
                    centroid[key] = (centroid.get(key, 0.0) + value) / 2.0
                matched = True
                break
        if not matched:
            clusters.append([text])
            cluster_vectors.append(dict(vector))
    return clusters


class SemanticPatternDetector(UsagePatternDetector):
    """Detect repeated improver prompts using semantic clustering."""

    def detect(self, *, window_days: int = 30) -> list[DetectedPattern]:
        """Return semantically clustered prompt patterns."""
        window = UsageWindow.last_days(window_days)
        rows = self._store.recall_usage(window)
        texts: list[str] = []
        for row in rows:
            if not row.improver_fired:
                continue
            if not row.activity.startswith(_IMPROVE_ACTIVITY_PREFIX):
                continue
            sample = row.improver_input_sample
            if sample and normalize_prompt_text(sample):
                texts.append(sample)
        clusters = cluster_prompt_texts_semantic(texts)
        patterns: list[DetectedPattern] = []
        for cluster in clusters:
            if len(cluster) < _MIN_OCCURRENCES:
                continue
            representative = cluster[0]
            patterns.append(
                DetectedPattern(
                    pattern_id=pattern_id_from_text(representative),
                    sample_text=representative,
                    occurrence_count=len(cluster),
                )
            )
        return sorted(patterns, key=lambda item: item.occurrence_count, reverse=True)


def create_pattern_detector(store: UsageStore, *, mode: str = "lexical") -> UsagePatternDetector:
    """Return the configured pattern detector backend."""
    if mode == "semantic":
        return SemanticPatternDetector(store)
    return UsagePatternDetector(store)
