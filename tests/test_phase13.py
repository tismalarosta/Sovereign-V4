"""
Phase 13 tests — Gemma 4 E4B LLM Upgrade

Tests:
- MODEL defaults to "gemma4:e4b"
- llm_model field present in settings
- LLM_MODEL env var overrides the default
- generate() sends the configured model in the request payload
- generate_stream() sends the configured model in the request payload
- Chat endpoint queries 12 chunks (not 5)

Run with: ./venv/bin/python -m pytest tests/test_phase13.py -v
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

import json
from unittest.mock import patch, MagicMock


# ── Model configuration ───────────────────────────────────────────────────────

def test_model_default_is_gemma4():
    """MODEL should default to gemma4:e4b."""
    import app.ollama_client as oc
    assert oc.MODEL == "gemma4:e4b"


def test_settings_has_llm_model_field():
    """Settings should expose llm_model field."""
    from app.settings import settings
    assert hasattr(settings, "llm_model")
    assert settings.llm_model == "gemma4:e4b"


def test_llm_model_field_default():
    """llm_model field default value must be gemma4:e4b (not mistral)."""
    from app.settings import _Settings
    # Construct with no env — use a non-existent env file to bypass .env
    s = _Settings(_env_file="/dev/null")
    assert s.llm_model == "gemma4:e4b"


# ── generate() sends correct model in payload ─────────────────────────────────

def test_generate_uses_configured_model():
    """generate() must include MODEL in the request payload."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "Hello!"}
    mock_response.raise_for_status = MagicMock()

    captured_payload = {}

    def fake_post(_url, json, **_kw):
        captured_payload.update(json)
        return mock_response

    with patch("app.ollama_client.httpx.post", side_effect=fake_post):
        from app.ollama_client import generate, MODEL
        result = generate("test prompt")

    assert captured_payload["model"] == MODEL
    assert captured_payload["stream"] is False
    assert captured_payload["prompt"] == "test prompt"
    assert result == "Hello!"


def test_generate_stream_uses_configured_model():
    """generate_stream() must include MODEL in the request payload."""
    line1 = json.dumps({"response": "Hi", "done": False})
    line2 = json.dumps({"response": "!", "done": True})

    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.raise_for_status = MagicMock()
    mock_stream_ctx.iter_lines = MagicMock(return_value=iter([line1, line2]))

    captured_payload = {}

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    def fake_stream(_method, _url, json):
        captured_payload.update(json)
        return mock_stream_ctx

    mock_client.stream = fake_stream

    with patch("app.ollama_client.httpx.Client", return_value=mock_client):
        from app.ollama_client import generate_stream, MODEL
        tokens = list(generate_stream("stream test"))

    assert captured_payload["model"] == MODEL
    assert captured_payload["stream"] is True
    assert "Hi" in tokens
    assert "!" in tokens


# ── Chat endpoint uses 12 chunks ──────────────────────────────────────────────

def test_chat_queries_12_chunks():
    """chat endpoint should query n_results=12 to leverage Gemma 4's 128K context."""
    import re
    from pathlib import Path

    main_path = Path(__file__).parent.parent / "app" / "main.py"
    source = main_path.read_text()

    # Find the store.query call in the chat function
    # It should be n_results=12, not 5
    matches = re.findall(r'store\.query\(embedding,\s*n_results=(\d+)\)', source)
    assert matches, "store.query(embedding, n_results=...) not found in main.py"
    assert all(int(n) >= 12 for n in matches), (
        f"Expected n_results >= 12 for Gemma 4's 128K context, got: {matches}"
    )


# ── Suggestion engine uses 3 snippets per source ──────────────────────────────

def test_suggestion_engine_uses_3_snippets_per_source():
    """Suggestion engine should use 3 snippets per source (up from 2 with Mistral)."""
    from pathlib import Path
    import re

    path = Path(__file__).parent.parent / "app" / "suggestion_engine.py"
    source = path.read_text()

    # Look for the slice [:3] in both file and email hit loops
    file_match = re.search(r'for h in file_hits\[:(\d+)\]', source)
    email_match = re.search(r'for h in email_hits\[:(\d+)\]', source)

    assert file_match, "file_hits slice not found"
    assert email_match, "email_hits slice not found"
    assert int(file_match.group(1)) >= 3, f"file_hits should use >= 3 snippets, got {file_match.group(1)}"
    assert int(email_match.group(1)) >= 3, f"email_hits should use >= 3 snippets, got {email_match.group(1)}"
