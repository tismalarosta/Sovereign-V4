"""
Security tests — Phase 6.5 SEC-07.

Tests: 401 without token, 429 rate limit, open_app bad name, open_finder system path.
"""

import pytest
from fastapi.testclient import TestClient

from app.auth import API_TOKEN
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
AUTH = {"Authorization": f"Bearer {API_TOKEN}"}


# ── SEC-01: Auth ───────────────────────────────────────────────────────────────

def test_no_token_returns_401():
    r = client.get("/snapshot")
    assert r.status_code == 401


def test_wrong_token_returns_401():
    r = client.get("/snapshot", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_valid_token_passes_auth():
    r = client.get("/snapshot", headers=AUTH)
    assert r.status_code == 200


def test_health_is_public():
    r = client.get("/health")
    assert r.status_code == 200


def test_dashboard_is_public():
    r = client.get("/dashboard")
    assert r.status_code == 200


# ── SEC-02: Rate limiting ─────────────────────────────────────────────────────

def test_chat_rate_limit_429():
    """11 chat requests in a row should trigger 429 on the 11th."""
    from app.rate_limiter import chat_limiter

    # Reset the bucket for our test IP
    chat_limiter._buckets["testclient"] = []

    # Hit the limiter directly 10 times (fills bucket)
    for _ in range(10):
        chat_limiter._buckets["testclient"].append(0.0)  # old timestamps

    # Use fresh timestamps to trigger the limit
    import time
    now = time.time()
    chat_limiter._buckets["testclient"] = [now] * 10

    # 11th request should be rate limited
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        chat_limiter.check("testclient")
    assert exc_info.value.status_code == 429

    # Clean up
    chat_limiter._buckets["testclient"] = []


# ── SEC-03: Execution hardening ───────────────────────────────────────────────

def test_open_app_rejects_bad_name():
    from app.execution_engine import _execute_open_app
    result = _execute_open_app({"app_name": "../../bin/sh"})
    assert result["success"] is False
    assert "Invalid" in result["message"]


def test_open_app_rejects_shell_injection():
    from app.execution_engine import _execute_open_app
    result = _execute_open_app({"app_name": "Safari; rm -rf ~"})
    assert result["success"] is False


def test_open_app_accepts_valid_name():
    """Valid name passes regex (actual open may fail if app absent, that's OK)."""
    from app.execution_engine import _SAFE_APP_NAME
    assert _SAFE_APP_NAME.match("Safari") is not None
    assert _SAFE_APP_NAME.match("Google Chrome") is not None
    assert _SAFE_APP_NAME.match("Final Cut Pro") is not None


def test_open_finder_rejects_system_path():
    from app.execution_engine import _execute_open_finder
    result = _execute_open_finder({"path": "/etc/passwd"})
    assert result["success"] is False
    assert "Access denied" in result["message"]


def test_open_finder_rejects_traversal():
    from app.execution_engine import _execute_open_finder
    result = _execute_open_finder({"path": "/Users/../etc"})
    assert result["success"] is False


def test_open_finder_accepts_home_subpath():
    from app.execution_engine import _execute_open_finder
    from pathlib import Path
    # Use a path guaranteed to exist under home
    result = _execute_open_finder({"path": str(Path.home() / "Downloads")})
    # May succeed or fail depending on whether Downloads exists, but must not be an auth error
    assert "Access denied" not in result.get("message", "")


# ── SEC-04: Input size caps ───────────────────────────────────────────────────

def test_chat_message_too_long_422():
    r = client.post("/chat", json={"message": "x" * 4001}, headers=AUTH)
    assert r.status_code == 422


def test_propose_action_type_too_long_422():
    r = client.post("/propose", json={"action_type": "x" * 101}, headers=AUTH)
    assert r.status_code == 422


def test_propose_too_many_params_422():
    params = {str(i): i for i in range(16)}  # 16 keys > 15
    r = client.post("/propose", json={"action_type": "open_app", "parameters": params}, headers=AUTH)
    assert r.status_code == 422
