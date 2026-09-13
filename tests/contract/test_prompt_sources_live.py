"""Optional live contract tests for allowlisted GitHub sources.

These tests require public internet and are excluded from default CI:

    pytest -m network
"""

from __future__ import annotations

import os

import pytest

from ylang.importer.policy import validate_fetch_url
from ylang.importer.refresh import github_commits_url
from ylang.importer.secure_fetch import FetchError, SecureFetcher


@pytest.mark.network
def test_live_prompts_chat_commits_https() -> None:
    if os.environ.get("YLANG_NETWORK_TESTS") != "1":
        pytest.skip("set YLANG_NETWORK_TESTS=1 to run live source contracts")
    fetcher = SecureFetcher()
    url = github_commits_url("f", "prompts.chat")
    validate_fetch_url(url, source_id="prompts-chat")
    try:
        response = fetcher.get(url, source_id="prompts-chat", content_kind="json")
    except FetchError as exc:
        pytest.skip(f"GitHub unavailable: {exc}")
    assert response.status_code == 200
    assert response.body
