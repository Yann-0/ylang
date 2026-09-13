"""SQLite store for prompt sources, source items, and refresh runs."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ylang.importer.policy import BUILTIN_SOURCE_SPECS, COPILOT_INCOMPATIBLE_NOTE, SourcePolicyError
from ylang.importer.source_types import (
    CandidateState,
    CompatibilityStatus,
    EvaluationRun,
    PromptSource,
    PromotionBaseline,
    RefreshSummary,
    SourceItem,
    TemplateProvenance,
    utcnow_iso,
)

_SOURCE_COLUMNS = (
    "source_id, name, adapter, canonical_url, repo_url, license_spdx, license_url, "
    "trust_tier, enabled, refresh_interval_hours, last_attempt_at, last_success_at, "
    "last_revision, last_etag, last_error, policy_version, created_at, updated_at, "
    "compatibility_status, compatibility_note"
)


def _source_from_row(row: sqlite3.Row | tuple[Any, ...]) -> PromptSource:
    values = tuple(row)
    return PromptSource(
        source_id=str(values[0]),
        name=str(values[1]),
        adapter=values[2],  # type: ignore[arg-type]
        canonical_url=str(values[3]),
        repo_url=str(values[4]) if values[4] is not None else None,
        license_spdx=str(values[5]),
        license_url=str(values[6]) if values[6] is not None else None,
        trust_tier=values[7],  # type: ignore[arg-type]
        enabled=bool(values[8]),
        refresh_interval_hours=int(values[9]),
        last_attempt_at=str(values[10]) if values[10] is not None else None,
        last_success_at=str(values[11]) if values[11] is not None else None,
        last_revision=str(values[12]) if values[12] is not None else None,
        last_etag=str(values[13]) if values[13] is not None else None,
        last_error=str(values[14]) if values[14] is not None else None,
        policy_version=str(values[15]),
        created_at=str(values[16]),
        updated_at=str(values[17]),
        compatibility_status=_compatibility_status(values),
        compatibility_note=(
            str(values[19]) if len(values) > 19 and values[19] is not None else None
        ),
    )


def _compatibility_status(values: tuple[Any, ...]) -> CompatibilityStatus:
    """Coerce a stored compatibility flag; unknown values become unverified."""
    raw = str(values[18]) if len(values) > 18 and values[18] else "unverified"
    if raw == "eligible":
        return "eligible"
    if raw == "incompatible":
        return "incompatible"
    return "unverified"


def _item_from_row(row: sqlite3.Row | tuple[Any, ...]) -> SourceItem:
    values = tuple(row)
    risk_reasons = tuple(json.loads(str(values[15] or "[]")))
    quality_reasons = tuple(json.loads(str(values[17] or "[]")))
    return SourceItem(
        item_id=str(values[0]),
        source_id=str(values[1]),
        upstream_item_id=str(values[2]),
        canonical_url=str(values[3]) if values[3] is not None else None,
        source_revision=str(values[4]) if values[4] is not None else None,
        content_hash=str(values[5]),
        normalized_fingerprint=str(values[6]),
        title=str(values[7]),
        body=str(values[8]),
        params_json=str(values[9]),
        metadata_json=str(values[10]),
        first_seen_at=str(values[11]),
        last_seen_at=str(values[12]),
        candidate_state=values[13],  # type: ignore[arg-type]
        risk_level=values[14],  # type: ignore[arg-type]
        risk_reasons=risk_reasons,
        quality_score=int(values[16]),
        quality_reasons=quality_reasons,
        task_family=values[18],  # type: ignore[arg-type]
        model_hint=str(values[19]) if values[19] is not None else None,
        duplicate_of_item_id=str(values[20]) if values[20] is not None else None,
        duplicate_template_id=str(values[21]) if values[21] is not None else None,
        linked_template_id=str(values[22]) if values[22] is not None else None,
        linked_template_version=int(values[23]) if values[23] is not None else None,
        license_spdx=str(values[24]) if values[24] is not None else None,
        adapter_version=str(values[25]),
        previous_body=str(values[26]) if values[26] is not None else None,
        previous_content_hash=str(values[27]) if values[27] is not None else None,
    )


class PromptSourceStore:
    """Persistence for prompt sources and quarantined upstream items."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def ensure_builtin_sources(self) -> None:
        """Insert built-in sources if missing; do not reset operator enabled flags."""
        now = utcnow_iso()
        for spec in BUILTIN_SOURCE_SPECS:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO prompt_sources (
                    source_id, name, adapter, canonical_url, repo_url,
                    license_spdx, license_url, trust_tier, enabled,
                    refresh_interval_hours, policy_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    spec["source_id"],
                    spec["name"],
                    spec["adapter"],
                    spec["canonical_url"],
                    spec["repo_url"],
                    spec["license_spdx"],
                    spec["license_url"],
                    spec["trust_tier"],
                    spec["enabled"],
                    spec["refresh_interval_hours"],
                    spec["policy_version"],
                    now,
                    now,
                ),
            )
        cols = {
            str(row[1])
            for row in self._connection.execute("PRAGMA table_info(prompt_sources)")
        }
        if "compatibility_status" in cols:
            self._connection.execute(
                """
                UPDATE prompt_sources
                SET compatibility_status = 'incompatible',
                    compatibility_note = ?
                WHERE source_id = 'github-awesome-copilot'
                  AND compatibility_status = 'unverified'
                """,
                (COPILOT_INCOMPATIBLE_NOTE,),
            )
        self._connection.commit()

    def list_sources(self) -> list[PromptSource]:
        """Return all source records."""
        cursor = self._connection.execute(
            f"SELECT {_SOURCE_COLUMNS} FROM prompt_sources ORDER BY source_id"
        )
        return [_source_from_row(row) for row in cursor.fetchall()]

    def get_source(self, source_id: str) -> PromptSource | None:
        """Return one source or None."""
        row = self._connection.execute(
            f"SELECT {_SOURCE_COLUMNS} FROM prompt_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        return _source_from_row(row) if row is not None else None

    def set_enabled(self, source_id: str, enabled: bool) -> PromptSource | None:
        """Enable or disable scheduled refresh for a source.

        Incompatible sources cannot be enabled: that would schedule ingestion of
        agents/skills/tools as if they were ordinary prompts.
        """
        source = self.get_source(source_id)
        if source is None:
            return None
        if enabled and source.compatibility_status == "incompatible":
            raise SourcePolicyError(
                "incompatible",
                source.compatibility_note
                or f"{source_id} is incompatible with the v1 prompt adapter",
            )
        now = utcnow_iso()
        self._connection.execute(
            """
            UPDATE prompt_sources
            SET enabled = ?, updated_at = ?
            WHERE source_id = ? AND source_id != 'manual-import'
            """,
            (int(enabled), now, source_id),
        )
        self._connection.commit()
        return self.get_source(source_id)

    def set_compatibility(
        self,
        source_id: str,
        status: str,
        note: str | None,
        *,
        disable: bool = False,
    ) -> None:
        """Record live layout compatibility. Optionally force-disable."""
        now = utcnow_iso()
        if disable:
            self._connection.execute(
                """
                UPDATE prompt_sources
                SET compatibility_status = ?, compatibility_note = ?,
                    enabled = 0, updated_at = ?
                WHERE source_id = ?
                """,
                (status, note, now, source_id),
            )
        else:
            self._connection.execute(
                """
                UPDATE prompt_sources
                SET compatibility_status = ?, compatibility_note = ?, updated_at = ?
                WHERE source_id = ?
                """,
                (status, note, now, source_id),
            )
        self._connection.commit()

    def mark_attempt(self, source_id: str) -> None:
        """Record that a refresh was attempted."""
        now = utcnow_iso()
        self._connection.execute(
            """
            UPDATE prompt_sources
            SET last_attempt_at = ?, last_error = NULL, updated_at = ?
            WHERE source_id = ?
            """,
            (now, now, source_id),
        )
        self._connection.commit()

    def mark_error(self, source_id: str, error: str) -> None:
        """Record a refresh error; keep last successful revision."""
        now = utcnow_iso()
        self._connection.execute(
            """
            UPDATE prompt_sources
            SET last_attempt_at = ?, last_error = ?, updated_at = ?
            WHERE source_id = ?
            """,
            (now, error[:2000], now, source_id),
        )
        self._connection.commit()

    def mark_success(
        self,
        source_id: str,
        *,
        revision: str | None,
        etag: str | None,
    ) -> None:
        """Record a successful refresh revision."""
        now = utcnow_iso()
        self._connection.execute(
            """
            UPDATE prompt_sources
            SET last_attempt_at = ?, last_success_at = ?, last_revision = ?,
                last_etag = ?, last_error = NULL, updated_at = ?
            WHERE source_id = ?
            """,
            (now, now, revision, etag, now, source_id),
        )
        self._connection.commit()

    def record_run(self, summary: RefreshSummary) -> None:
        """Persist a refresh summary row."""
        self._connection.execute(
            """
            INSERT INTO prompt_refresh_runs (
                source_id, started_at, finished_at, revision_before, revision_after,
                status, new_count, changed_count, removed_count, duplicate_count,
                quarantined_count, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.source_id,
                utcnow_iso(),
                utcnow_iso(),
                summary.revision_before,
                summary.revision_after,
                summary.status,
                summary.new,
                summary.changed,
                summary.removed,
                summary.duplicates,
                summary.quarantined,
                summary.error,
            ),
        )
        self._connection.commit()

    def get_item(self, item_id: str) -> SourceItem | None:
        """Return one source item."""
        row = self._connection.execute(
            "SELECT * FROM prompt_source_items WHERE item_id = ?",
            (item_id,),
        ).fetchone()
        return _item_from_row(row) if row is not None else None

    def get_by_upstream(self, source_id: str, upstream_item_id: str) -> SourceItem | None:
        """Return the item for a source + upstream identity."""
        row = self._connection.execute(
            """
            SELECT * FROM prompt_source_items
            WHERE source_id = ? AND upstream_item_id = ?
            """,
            (source_id, upstream_item_id),
        ).fetchone()
        return _item_from_row(row) if row is not None else None

    def list_items(
        self,
        *,
        source_id: str | None = None,
        state: CandidateState | None = None,
        states: tuple[str, ...] | None = None,
        limit: int = 200,
    ) -> list[SourceItem]:
        """List source items, newest last_seen first."""
        clauses: list[str] = []
        params: list[object] = []
        if source_id:
            clauses.append("source_id = ?")
            params.append(source_id)
        if state:
            clauses.append("candidate_state = ?")
            params.append(state)
        elif states:
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"candidate_state IN ({placeholders})")
            params.extend(states)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self._connection.execute(
            f"""
            SELECT * FROM prompt_source_items
            {where}
            ORDER BY last_seen_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        return [_item_from_row(row) for row in cursor.fetchall()]

    def rejected_hashes(self) -> set[str]:
        """Content hashes that were explicitly rejected (any source)."""
        cursor = self._connection.execute(
            "SELECT DISTINCT content_hash FROM prompt_source_items WHERE candidate_state = 'rejected'"
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def find_duplicate_item(
        self,
        *,
        content_hash: str,
        fingerprint: str,
        title_normalized: str,
        exclude_item_id: str | None = None,
    ) -> SourceItem | None:
        """Return an earlier item matching hash, fingerprint, or title."""
        row = self._connection.execute(
            """
            SELECT * FROM prompt_source_items
            WHERE (content_hash = ? OR normalized_fingerprint = ?
                   OR lower(trim(title)) = ?)
              AND (? IS NULL OR item_id != ?)
            ORDER BY first_seen_at ASC
            LIMIT 1
            """,
            (content_hash, fingerprint, title_normalized, exclude_item_id, exclude_item_id),
        ).fetchone()
        return _item_from_row(row) if row is not None else None

    def upsert_item(self, item: SourceItem) -> None:
        """Insert or replace a source item row."""
        self._connection.execute(
            """
            INSERT INTO prompt_source_items (
                item_id, source_id, upstream_item_id, canonical_url, source_revision,
                content_hash, normalized_fingerprint, title, body, params_json,
                metadata_json, first_seen_at, last_seen_at, candidate_state,
                risk_level, risk_reasons_json, quality_score, quality_reasons_json,
                task_family, model_hint, duplicate_of_item_id, duplicate_template_id,
                linked_template_id, linked_template_version, license_spdx, adapter_version,
                previous_body, previous_content_hash
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(item_id) DO UPDATE SET
                canonical_url = excluded.canonical_url,
                source_revision = excluded.source_revision,
                content_hash = excluded.content_hash,
                normalized_fingerprint = excluded.normalized_fingerprint,
                title = excluded.title,
                body = excluded.body,
                params_json = excluded.params_json,
                metadata_json = excluded.metadata_json,
                last_seen_at = excluded.last_seen_at,
                candidate_state = excluded.candidate_state,
                risk_level = excluded.risk_level,
                risk_reasons_json = excluded.risk_reasons_json,
                quality_score = excluded.quality_score,
                quality_reasons_json = excluded.quality_reasons_json,
                task_family = excluded.task_family,
                model_hint = excluded.model_hint,
                duplicate_of_item_id = excluded.duplicate_of_item_id,
                duplicate_template_id = excluded.duplicate_template_id,
                linked_template_id = excluded.linked_template_id,
                linked_template_version = excluded.linked_template_version,
                license_spdx = excluded.license_spdx,
                adapter_version = excluded.adapter_version,
                previous_body = excluded.previous_body,
                previous_content_hash = excluded.previous_content_hash
            """,
            (
                item.item_id,
                item.source_id,
                item.upstream_item_id,
                item.canonical_url,
                item.source_revision,
                item.content_hash,
                item.normalized_fingerprint,
                item.title,
                item.body,
                item.params_json,
                item.metadata_json,
                item.first_seen_at,
                item.last_seen_at,
                item.candidate_state,
                item.risk_level,
                json.dumps(list(item.risk_reasons)),
                item.quality_score,
                json.dumps(list(item.quality_reasons)),
                item.task_family,
                item.model_hint,
                item.duplicate_of_item_id,
                item.duplicate_template_id,
                item.linked_template_id,
                item.linked_template_version,
                item.license_spdx,
                item.adapter_version,
                item.previous_body,
                item.previous_content_hash,
            ),
        )

    def set_state(self, item_id: str, state: CandidateState) -> SourceItem | None:
        """Update candidate lifecycle state."""
        self._connection.execute(
            "UPDATE prompt_source_items SET candidate_state = ? WHERE item_id = ?",
            (state, item_id),
        )
        self._connection.commit()
        return self.get_item(item_id)

    def link_promotion(
        self,
        item_id: str,
        *,
        template_id: str,
        version: int,
    ) -> None:
        """Mark an item promoted and link the immutable template version."""
        now = utcnow_iso()
        item = self.get_item(item_id)
        if item is None:
            raise KeyError(item_id)
        self._connection.execute(
            """
            UPDATE prompt_source_items
            SET candidate_state = 'promoted',
                linked_template_id = ?,
                linked_template_version = ?
            WHERE item_id = ?
            """,
            (template_id, version, item_id),
        )
        self._connection.execute(
            """
            INSERT INTO template_provenance (
                template_id, version, item_id, source_id,
                upstream_revision, content_hash, canonical_url, promoted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                version,
                item_id,
                item.source_id,
                item.source_revision,
                item.content_hash,
                item.canonical_url,
                now,
            ),
        )
        self._connection.commit()

    def provenance_for_template(self, template_id: str) -> list[TemplateProvenance]:
        """Return provenance rows for a template, newest version first."""
        cursor = self._connection.execute(
            """
            SELECT template_id, version, item_id, source_id,
                   upstream_revision, content_hash, canonical_url, promoted_at
            FROM template_provenance
            WHERE template_id = ?
            ORDER BY version DESC
            """,
            (template_id,),
        )
        rows: list[TemplateProvenance] = []
        for row in cursor.fetchall():
            rows.append(
                TemplateProvenance(
                    template_id=str(row[0]),
                    version=int(row[1]),
                    item_id=str(row[2]),
                    source_id=str(row[3]),
                    upstream_revision=str(row[4]) if row[4] is not None else None,
                    content_hash=str(row[5]),
                    canonical_url=str(row[6]) if row[6] is not None else None,
                    promoted_at=str(row[7]),
                )
            )
        return rows

    def save_evaluation_snapshot(
        self,
        *,
        item_id: str,
        vs_template_id: str | None,
        vs_template_version: int | None,
        current_accept_rate: float | None,
        current_avg_cost: float | None,
        current_avg_latency_ms: float | None,
        current_injections: int,
        current_body_hash: str | None,
        candidate_content_hash: str,
        quality_score: int,
        risk_level: str,
        body_diff_ratio: float | None,
        fixture_hash: str | None,
        fixture_chars: int | None,
        experiment_id: str,
    ) -> None:
        """Upsert a local candidate-vs-current comparison snapshot."""
        now = utcnow_iso()
        self._connection.execute(
            """
            INSERT INTO prompt_evaluation_snapshots (
                item_id, vs_template_id, vs_template_version,
                current_accept_rate, current_avg_cost, current_avg_latency_ms,
                current_injections, current_body_hash, candidate_content_hash,
                quality_score, risk_level, body_diff_ratio, fixture_hash,
                fixture_chars, experiment_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                vs_template_id = excluded.vs_template_id,
                vs_template_version = excluded.vs_template_version,
                current_accept_rate = excluded.current_accept_rate,
                current_avg_cost = excluded.current_avg_cost,
                current_avg_latency_ms = excluded.current_avg_latency_ms,
                current_injections = excluded.current_injections,
                current_body_hash = excluded.current_body_hash,
                candidate_content_hash = excluded.candidate_content_hash,
                quality_score = excluded.quality_score,
                risk_level = excluded.risk_level,
                body_diff_ratio = excluded.body_diff_ratio,
                fixture_hash = excluded.fixture_hash,
                fixture_chars = excluded.fixture_chars,
                experiment_id = excluded.experiment_id,
                created_at = excluded.created_at
            """,
            (
                item_id,
                vs_template_id,
                vs_template_version,
                current_accept_rate,
                current_avg_cost,
                current_avg_latency_ms,
                current_injections,
                current_body_hash,
                candidate_content_hash,
                quality_score,
                risk_level,
                body_diff_ratio,
                fixture_hash,
                fixture_chars,
                experiment_id,
                now,
            ),
        )
        self._connection.commit()

    def save_promotion_baseline(
        self,
        *,
        template_id: str,
        version: int,
        item_id: str,
        accept_rate: float | None,
        avg_cost: float | None,
        avg_latency_ms: float | None,
        injections: int,
    ) -> PromotionBaseline:
        """Record pre-promotion outcomes for later delta reports."""
        now = utcnow_iso()
        self._connection.execute(
            """
            INSERT OR REPLACE INTO prompt_promotion_baselines (
                template_id, version, item_id, accept_rate, avg_cost,
                avg_latency_ms, injections, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                version,
                item_id,
                accept_rate,
                avg_cost,
                avg_latency_ms,
                injections,
                now,
            ),
        )
        self._connection.commit()
        return PromotionBaseline(
            template_id=template_id,
            version=version,
            item_id=item_id,
            accept_rate=accept_rate,
            avg_cost=avg_cost,
            avg_latency_ms=avg_latency_ms,
            injections=injections,
            captured_at=now,
        )

    def list_promotion_baselines(self) -> list[PromotionBaseline]:
        """Return promote-time baselines, newest version first."""
        cursor = self._connection.execute(
            """
            SELECT template_id, version, item_id, accept_rate, avg_cost,
                   avg_latency_ms, injections, captured_at
            FROM prompt_promotion_baselines
            ORDER BY captured_at DESC
            """
        )
        rows: list[PromotionBaseline] = []
        for row in cursor.fetchall():
            rows.append(
                PromotionBaseline(
                    template_id=str(row[0]),
                    version=int(row[1]),
                    item_id=str(row[2]),
                    accept_rate=float(row[3]) if row[3] is not None else None,
                    avg_cost=float(row[4]) if row[4] is not None else None,
                    avg_latency_ms=float(row[5]) if row[5] is not None else None,
                    injections=int(row[6]),
                    captured_at=str(row[7]),
                )
            )
        return rows

    def try_acquire_refresh_lease(
        self, source_id: str, *, owner: str, ttl_sec: int
    ) -> bool:
        """Acquire a cross-process refresh lease. Expired leases are stolen."""
        now = utcnow_iso()
        self._connection.execute(
            "DELETE FROM prompt_refresh_leases WHERE source_id = ? AND expires_at <= ?",
            (source_id, now),
        )
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO prompt_refresh_leases (
                source_id, owner, acquired_at, expires_at
            ) VALUES (?, ?, ?, ?)
            """,
            (source_id, owner, now, _iso_plus_seconds(now, ttl_sec)),
        )
        self._connection.commit()
        return cursor.rowcount == 1

    def release_refresh_lease(self, source_id: str, *, owner: str) -> None:
        """Release a lease only if this owner still holds it."""
        self._connection.execute(
            "DELETE FROM prompt_refresh_leases WHERE source_id = ? AND owner = ?",
            (source_id, owner),
        )
        self._connection.commit()

    def save_evaluation_run(self, run: EvaluationRun) -> None:
        """Persist an inspect or execute evaluation run (append-only)."""
        self._connection.execute(
            """
            INSERT INTO prompt_evaluation_runs (
                run_id, item_id, mode, evidence_class, vs_template_id,
                vs_template_version, vs_content_hash, candidate_content_hash,
                model, authorized, budget_usd, cost_usd, baseline_output,
                candidate_output, baseline_error, candidate_error,
                baseline_latency_ms, candidate_latency_ms,
                baseline_prompt_tokens, candidate_prompt_tokens,
                baseline_completion_tokens, candidate_completion_tokens,
                evaluator_json, fixture_hash, created_at, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.run_id,
                run.item_id,
                run.mode,
                run.evidence_class,
                run.vs_template_id,
                run.vs_template_version,
                run.vs_content_hash,
                run.candidate_content_hash,
                run.model,
                int(run.authorized),
                run.budget_usd,
                run.cost_usd,
                run.baseline_output,
                run.candidate_output,
                run.baseline_error,
                run.candidate_error,
                run.baseline_latency_ms,
                run.candidate_latency_ms,
                run.baseline_prompt_tokens,
                run.candidate_prompt_tokens,
                run.baseline_completion_tokens,
                run.candidate_completion_tokens,
                run.evaluator_json,
                run.fixture_hash,
                run.created_at,
                run.note,
            ),
        )
        self._connection.commit()

    def list_evaluation_runs(self, item_id: str, *, limit: int = 20) -> list[EvaluationRun]:
        """Return recent evaluation runs for a candidate, newest first."""
        cursor = self._connection.execute(
            """
            SELECT run_id, item_id, mode, evidence_class, vs_template_id,
                   vs_template_version, vs_content_hash, candidate_content_hash,
                   model, authorized, budget_usd, cost_usd, baseline_output,
                   candidate_output, baseline_error, candidate_error,
                   baseline_latency_ms, candidate_latency_ms,
                   baseline_prompt_tokens, candidate_prompt_tokens,
                   baseline_completion_tokens, candidate_completion_tokens,
                   evaluator_json, fixture_hash, created_at, note
            FROM prompt_evaluation_runs
            WHERE item_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (item_id, limit),
        )
        return [_evaluation_run_from_row(row) for row in cursor.fetchall()]

    def pending_review_count(self) -> int:
        """Count candidates waiting for human review."""
        row = self._connection.execute(
            """
            SELECT COUNT(*) FROM prompt_source_items
            WHERE candidate_state IN (
                'candidate_new', 'candidate_changed', 'quarantined', 'reviewed'
            )
            """
        ).fetchone()
        return int(row[0]) if row else 0

    def commit(self) -> None:
        """Commit the current transaction."""
        self._connection.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self._connection.rollback()


def _iso_plus_seconds(iso: str, seconds: int) -> str:
    """Return ``iso`` plus ``seconds`` as an ISO-8601 UTC timestamp."""
    from datetime import datetime, timedelta, timezone

    value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (value + timedelta(seconds=seconds)).isoformat()


def _evaluation_run_from_row(row: sqlite3.Row | tuple[Any, ...]) -> EvaluationRun:
    """Map a prompt_evaluation_runs row to ``EvaluationRun``."""
    values = tuple(row)
    return EvaluationRun(
        run_id=str(values[0]),
        item_id=str(values[1]),
        mode=values[2],  # type: ignore[arg-type]
        evidence_class=values[3],  # type: ignore[arg-type]
        vs_template_id=str(values[4]) if values[4] is not None else None,
        vs_template_version=int(values[5]) if values[5] is not None else None,
        vs_content_hash=str(values[6]) if values[6] is not None else None,
        candidate_content_hash=str(values[7]),
        model=str(values[8]) if values[8] is not None else None,
        authorized=bool(values[9]),
        budget_usd=float(values[10]) if values[10] is not None else None,
        cost_usd=float(values[11]),
        baseline_output=str(values[12]) if values[12] is not None else None,
        candidate_output=str(values[13]) if values[13] is not None else None,
        baseline_error=str(values[14]) if values[14] is not None else None,
        candidate_error=str(values[15]) if values[15] is not None else None,
        baseline_latency_ms=int(values[16]) if values[16] is not None else None,
        candidate_latency_ms=int(values[17]) if values[17] is not None else None,
        baseline_prompt_tokens=int(values[18]) if values[18] is not None else None,
        candidate_prompt_tokens=int(values[19]) if values[19] is not None else None,
        baseline_completion_tokens=int(values[20]) if values[20] is not None else None,
        candidate_completion_tokens=int(values[21]) if values[21] is not None else None,
        evaluator_json=str(values[22]),
        fixture_hash=str(values[23]) if values[23] is not None else None,
        created_at=str(values[24]),
        note=str(values[25]),
    )


def source_store_from_connection(connection: sqlite3.Connection) -> PromptSourceStore:
    """Attach a source store and seed built-in sources."""
    store = PromptSourceStore(connection)
    store.ensure_builtin_sources()
    return store
