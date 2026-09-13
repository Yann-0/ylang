"""Optional live contract tests for allowlisted GitHub sources.

These tests require public internet and are excluded from default CI:

    YLANG_NETWORK_TESTS=1 pytest -m network

A passing live contract is not proof that imported prompts are high quality.
"""

from __future__ import annotations

import json
import os

import pytest

from ylang.importer.adapters.awesome_copilot import AwesomeCopilotAdapter
from ylang.importer.adapters.fabric import FabricPatternsAdapter
from ylang.importer.adapters.prompts_chat import PromptsChatAdapter
from ylang.importer.policy import license_text_matches, validate_fetch_url
from ylang.importer.refresh import (
    github_commits_url,
    github_license_url,
    github_tree_url,
    parse_github_tree,
)
from ylang.importer.secure_fetch import FetchError, SecureFetcher


def _require_network() -> None:
    if os.environ.get("YLANG_NETWORK_TESTS") != "1":
        pytest.skip("set YLANG_NETWORK_TESTS=1 to run live source contracts")


def _live_sha(fetcher: SecureFetcher, owner: str, repo: str, source_id: str) -> str:
    url = github_commits_url(owner, repo)
    validate_fetch_url(url, source_id=source_id)
    try:
        response = fetcher.get(url, source_id=source_id, content_kind="json")
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    data = json.loads(response.body.decode("utf-8"))
    sha = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(sha, str) or not sha:
        pytest.skip("malformed GitHub commit payload")
    return sha


@pytest.mark.network
def test_live_prompts_chat_commits_https() -> None:
    _require_network()
    fetcher = SecureFetcher()
    url = github_commits_url("f", "prompts.chat")
    validate_fetch_url(url, source_id="prompts-chat")
    try:
        response = fetcher.get(url, source_id="prompts-chat", content_kind="json")
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    assert response.status_code == 200
    assert response.body


@pytest.mark.network
def test_live_prompts_chat_csv_and_cc0_license() -> None:
    _require_network()
    fetcher = SecureFetcher()
    sha = _live_sha(fetcher, "f", "prompts.chat", "prompts-chat")
    license_url = github_license_url("f", "prompts.chat", sha)
    csv_url = f"https://raw.githubusercontent.com/f/prompts.chat/{sha}/prompts.csv"
    validate_fetch_url(license_url, source_id="prompts-chat")
    validate_fetch_url(csv_url, source_id="prompts-chat")
    try:
        license_resp = fetcher.get(
            license_url, source_id="prompts-chat", content_kind="license"
        )
        csv_resp = fetcher.get(csv_url, source_id="prompts-chat", content_kind="csv")
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    text = license_resp.text()
    assert license_text_matches(text, "CC0-1.0")
    assert "cc0" in text.lower()
    items = PromptsChatAdapter().parse({"prompts.csv": csv_resp.text()}, revision=sha)
    assert items, "prompts.csv must still contain act/prompt rows"


@pytest.mark.network
def test_live_awesome_copilot_has_no_v1_prompt_files() -> None:
    _require_network()
    fetcher = SecureFetcher()
    sha = _live_sha(fetcher, "github", "awesome-copilot", "github-awesome-copilot")
    tree_url = github_tree_url("github", "awesome-copilot", sha)
    validate_fetch_url(tree_url, source_id="github-awesome-copilot")
    try:
        tree = fetcher.get(
            tree_url, source_id="github-awesome-copilot", content_kind="json"
        )
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    paths, truncated = parse_github_tree(tree.body)
    assert truncated is False
    selected = AwesomeCopilotAdapter().select_paths(paths)
    assert selected == []
    agents = [path for path in paths if path.startswith("agents/")]
    skills = [path for path in paths if path.startswith("skills/")]
    assert agents and skills


@pytest.mark.network
def test_live_fabric_patterns_system_md() -> None:
    _require_network()
    fetcher = SecureFetcher()
    sha = _live_sha(fetcher, "danielmiessler", "Fabric", "fabric-patterns")
    tree_url = github_tree_url("danielmiessler", "Fabric", sha)
    license_url = github_license_url("danielmiessler", "Fabric", sha)
    validate_fetch_url(tree_url, source_id="fabric-patterns")
    try:
        tree = fetcher.get(tree_url, source_id="fabric-patterns", content_kind="json")
        license_resp = fetcher.get(
            license_url, source_id="fabric-patterns", content_kind="license"
        )
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    paths, truncated = parse_github_tree(tree.body)
    assert truncated is False
    selected = FabricPatternsAdapter().select_paths(paths)
    assert selected, "Fabric must still expose data/patterns/*/system.md"
    assert license_text_matches(license_resp.text(), "MIT")
