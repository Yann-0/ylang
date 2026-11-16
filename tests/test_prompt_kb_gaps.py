"""Prompt KB gaps: local skills, skill adapter, retrieval, drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from ylang.cli.prompts import run_prompts_cli
from ylang.importer.adapters.awesome_copilot import AwesomeCopilotAdapter
from ylang.importer.adapters.local_skills import LocalSkillsAdapter, select_local_paths
from ylang.importer.auto_apply import auto_apply_linked_updates
from ylang.importer.drift import collect_prompt_drift
from ylang.importer.ingest import ingest_parsed_items
from ylang.importer.local_refresh import load_local_skill_items
from ylang.importer.policy import SourcePolicyError, validate_auto_apply_updates
from ylang.importer.promote import promote_candidate
from ylang.importer.refresh import open_source_store, refresh_source
from ylang.importer.source_types import ParsedUpstreamItem, utcnow_iso
from ylang.library import open_library
from ylang.library.retrieval import select_reference_prompts

LOCAL_SKILLS = Path(__file__).parent / "fixtures" / "operator_skills"
COPILOT_SKILL = (
    Path(__file__).parent / "fixtures" / "awesome_copilot" / "skills" / "review-pr" / "SKILL.md"
).read_text(encoding="utf-8")


def test_public_source_cannot_enable_auto_apply(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        source = store.get_source("prompts-chat")
        assert source is not None
        with pytest.raises(SourcePolicyError, match="operator-owned"):
            validate_auto_apply_updates(source, True)
        with pytest.raises(SourcePolicyError, match="operator-owned"):
            store.set_auto_apply_updates("prompts-chat", True)
    finally:
        library.close()


def test_operator_local_refresh_and_auto_apply_linked(tmp_path: Path) -> None:
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        store.set_local_path("operator-local-skills", str(LOCAL_SKILLS))
        store.set_auto_apply_updates("operator-local-skills", True)
        store.set_enabled("operator-local-skills", True)
        first = refresh_source(
            store,
            library,
            "operator-local-skills",
            parsed_items=None,
        )
        assert first.status == "success"
        assert first.new >= 1
        item_id = "operator-local-skills:review-pr/SKILL.md"
        promoted = promote_candidate(store, library, item_id, template_id="review-pr-skill")
        assert promoted.version == 1
        changed = ParsedUpstreamItem(
            upstream_item_id="review-pr/SKILL.md",
            title="Review PR",
            body="Updated operator skill body with more detail.",
            metadata={"artifact": "skill"},
        )
        source = store.get_source("operator-local-skills")
        assert source is not None
        ingest_parsed_items(
            store,
            library,
            source,
            [changed],
            revision="rev-2",
            mark_removed=False,
        )
        row = store.get_item(item_id)
        assert row is not None
        assert row.candidate_state == "candidate_changed"
        applied = auto_apply_linked_updates(store, library, source)
        assert applied == 1
        template = library.recall("review-pr-skill")
        assert template is not None
        assert template.version == 2
        assert "Updated operator" in template.body
        row = store.get_item(item_id)
        assert row is not None
        assert row.candidate_state == "promoted"
    finally:
        library.close()


def test_empty_operator_dir_does_not_lock_source(tmp_path: Path) -> None:
    root = tmp_path / "skills-root"
    root.mkdir()
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        store.set_compatibility(
            "operator-local-skills",
            "incompatible",
            "local path is not a directory: /old",
            disable=True,
        )
        store.set_local_path("operator-local-skills", str(root))
        cleared = store.get_source("operator-local-skills")
        assert cleared is not None
        assert cleared.compatibility_status == "unverified"
        assert cleared.last_error is None
        store.set_enabled("operator-local-skills", True)
        summary = refresh_source(store, library, "operator-local-skills")
        assert summary.status == "blocked"
        assert "no SKILL.md" in (summary.error or "")
        after = store.get_source("operator-local-skills")
        assert after is not None
        assert after.enabled is True
        assert after.compatibility_status != "incompatible"
    finally:
        library.close()


def test_operator_new_file_stays_candidate_until_promote(tmp_path: Path) -> None:
    root = tmp_path / "skills-root"
    (root / "alpha").mkdir(parents=True)
    skill = root / "alpha" / "SKILL.md"
    skill.write_text(
        "---\nname: alpha\ndescription: Alpha skill\n---\nAlpha body\n",
        encoding="utf-8",
    )
    library = open_library(tmp_path / "db.sqlite")
    store = open_source_store(library)
    try:
        store.set_local_path("operator-local-skills", str(root))
        summary = refresh_source(store, library, "operator-local-skills")
        assert summary.status == "success"
        item = store.get_item("operator-local-skills:alpha/SKILL.md")
        assert item is not None
        assert item.candidate_state == "candidate_new"
        assert item.linked_template_id is None
        assert library.recall("alpha") is None
    finally:
        library.close()


def test_awesome_copilot_ingests_skills_not_agents() -> None:
    adapter = AwesomeCopilotAdapter()
    selected = adapter.select_paths(
        [
            "skills/review-pr/SKILL.md",
            "prompts/review-pr.prompt.md",
            "agents/coder.agent.md",
            "skills/foo/SKILL.md",
            "instructions/foo.md",
        ]
    )
    assert "skills/review-pr/SKILL.md" in selected
    assert "prompts/review-pr.prompt.md" in selected
    assert "agents/coder.agent.md" not in selected
    items = adapter.parse(
        {
            "skills/review-pr/SKILL.md": COPILOT_SKILL,
            "agents/coder.agent.md": "skip",
        },
        revision="sha",
    )
    assert len(items) == 1
    assert items[0].metadata.get("artifact") == "skill"
    assert items[0].metadata.get("tools") is None


def test_retrieval_prefers_linked_skill_with_fts(library) -> None:
    from ylang.library.search import index_template
    from ylang.library.types import TemplateParam

    library.save(
        "generic-template",
        name="Generic",
        body="unrelated database migration text",
        params=[],
        source="user",
        visibility="public",
        tags=["other"],
    )
    library.save(
        "linked-skill-template",
        name="Linked skill",
        body="review pull request checklist security tests",
        params=[TemplateParam(name="topic", description="Topic")],
        source="user",
        visibility="private",
        tags=["artifact:skill", "code"],
    )
    index_template(
        library._connection,
        template_id="linked-skill-template",
        name="Linked skill",
        body="review pull request checklist security tests",
        tags=["artifact:skill", "code"],
    )
    library._connection.execute(
        """
        INSERT INTO template_provenance (
            template_id, version, item_id, source_id,
            upstream_revision, content_hash, canonical_url, promoted_at
        ) VALUES (?, 1, ?, ?, ?, ?, ?, ?)
        """,
        (
            "linked-skill-template",
            "operator-local-skills:review-pr/SKILL.md",
            "operator-local-skills",
            "rev",
            "hash",
            None,
            utcnow_iso(),
        ),
    )
    library._connection.commit()
    results = select_reference_prompts(
        library,
        "please review this pull request for security issues",
        "edit_file",
        limit=2,
    )
    assert results
    assert results[0].template_id == "linked-skill-template"


def test_drift_report_and_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "skills"
    (root / "review-pr").mkdir(parents=True)
    (root / "review-pr" / "SKILL.md").write_text(
        "---\nname: review-pr\ndescription: Review\n---\nBody one\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "ylang.db"
    monkeypatch.setenv("YLANG_STORAGE_PATH", str(db_path))
    library = open_library(db_path)
    store = open_source_store(library)
    try:
        store.set_local_path("operator-local-skills", str(root))
        refresh_source(store, library, "operator-local-skills")
        promote_candidate(
            store,
            library,
            "operator-local-skills:review-pr/SKILL.md",
            template_id="drift-skill",
        )
        source = store.get_source("operator-local-skills")
        assert source is not None
        ingest_parsed_items(
            store,
            library,
            source,
            [
                ParsedUpstreamItem(
                    upstream_item_id="review-pr/SKILL.md",
                    title="Review",
                    body="changed upstream body",
                )
            ],
            revision="rev-drift",
            mark_removed=False,
        )
        (root / "new-skill").mkdir()
        (root / "new-skill" / "SKILL.md").write_text(
            "---\nname: new-skill\ndescription: New\n---\nNew body\n",
            encoding="utf-8",
        )
        refresh_source(store, library, "operator-local-skills")
        report = collect_prompt_drift(store)
        assert report.promoted_drifted
        assert any(
            row.item_id == "operator-local-skills:review-pr/SKILL.md"
            for row in report.promoted_drifted
        )
        assert any(
            row.item_id == "operator-local-skills:new-skill/SKILL.md"
            for row in report.operator_unlinked_new
        )
    finally:
        library.close()
    assert run_prompts_cli(["drift"]) == 0


def test_local_path_scan(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "pkg" / "SKILL.md").parent.mkdir(parents=True)
    (root / "pkg" / "SKILL.md").write_text("---\nname: pkg\ndescription: P\n---\n", encoding="utf-8")
    paths = select_local_paths(root)
    assert paths == ["pkg/SKILL.md"]
    items, revision, _ = load_local_skill_items(root)
    assert len(items) == 1
    assert revision


@pytest.fixture
def library(tmp_path: Path):
    lib = open_library(tmp_path / "library.db")
    yield lib
    lib.close()