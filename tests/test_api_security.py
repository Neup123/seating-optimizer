"""Local API boundary tests: remote denial, request sizes, solver limits, and replay."""
from __future__ import annotations

import asyncio
import base64

import httpx

from seating_optimizer.api.app import (
    MAX_BODY_BYTES, LocalApiBoundary, _trusted_local_client, app,
)


async def request(host, method, path, **kwargs):
    transport = httpx.ASGITransport(app=app, client=(host, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_only_loopback_is_allowed_not_forwarded_host_headers():
    assert _trusted_local_client("127.0.0.1")
    assert _trusted_local_client("::1")
    assert not _trusted_local_client("198.51.100.11")
    assert not _trusted_local_client("localhost.example")
    response = asyncio.run(request("198.51.100.11", "GET", "/healthz",
                                   headers={"X-Forwarded-For": "127.0.0.1"}))
    assert response.status_code == 403
    assert "Local-only" in response.text


def test_local_request_reaches_actual_api_and_json_body_is_replayed():
    health = asyncio.run(request("127.0.0.1", "GET", "/healthz"))
    assert health.status_code == 200
    source = b"Name,Size\nLocal Test,2\n"
    imported = asyncio.run(request("::1", "POST", "/v1/import", json={
        "filename": "guests.csv", "content_base64": base64.b64encode(source).decode("ascii")
    }))
    assert imported.status_code == 200, imported.text
    assert len(imported.json()["guests"]) == 2


def test_declared_body_above_limit_rejected_before_json_parse():
    response = asyncio.run(request("127.0.0.1", "POST", "/v1/solve",
        content=b"{}", headers={"Content-Length": str(MAX_BODY_BYTES + 1),
                                 "Content-Type": "application/json"}))
    assert response.status_code == 413


def test_solve_time_limit_is_capped_for_local_api():
    payload = {"session_id": "guard", "config": {"time_limit_seconds": 999},
               "zones": [], "tables": [], "guests": []}
    response = asyncio.run(request("127.0.0.1", "POST", "/v1/solve", json=payload))
    assert response.status_code == 422
    assert "60 s" in response.text


def test_safe_default_request_still_gets_pydantic_validation():
    response = asyncio.run(request("127.0.0.1", "POST", "/v2/solve", json={
        "session_id": "guard", "zones": [], "tables": [], "guests": []}))
    assert response.status_code == 422  # Domain validation, not an API security bypass.
