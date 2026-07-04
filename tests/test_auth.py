"""Tests for HTTP bearer token middleware."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from ylang.mcp.auth import BearerTokenMiddleware


async def _ok(_request: object) -> PlainTextResponse:
    return PlainTextResponse("ok")


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=[Route("/", _ok)])
    wrapped = BearerTokenMiddleware(app, "secret-token")
    return TestClient(wrapped)


def test_bearer_auth_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 401


def test_bearer_auth_rejects_wrong_token(client: TestClient) -> None:
    response = client.get("/", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_bearer_auth_accepts_valid_token(client: TestClient) -> None:
    response = client.get("/", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.text == "ok"
