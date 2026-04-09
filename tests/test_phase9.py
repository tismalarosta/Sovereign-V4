"""
Phase 9 tests — macOS Deep Integration

Tests:
- Policy engine: MAC-01–03 actions classified correctly
- Notes connector: surface guard (_is_blocked)
- Automator: input sanitization (show_notification, run_shortcut name validation)
- Confidence: new action types have entries

Run with: ./venv/bin/python -m pytest tests/test_phase9.py -v
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))


# ── Policy engine: MAC-01 (Contacts) ──────────────────────────────────────────

from app.policy_engine import classify, RiskTier


def test_open_contacts_card_is_low():
    d = classify("open_contacts_card")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


# ── Policy engine: MAC-03 (Automator) ─────────────────────────────────────────

def test_set_volume_is_low():
    d = classify("set_volume")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_get_frontmost_app_is_low():
    d = classify("get_frontmost_app")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_show_notification_is_low():
    d = classify("show_notification")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_run_shortcut_is_medium():
    d = classify("run_shortcut")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True


# ── Policy engine: MAC-02 (Notes) ─────────────────────────────────────────────

def test_create_note_is_medium():
    d = classify("create_note")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True


def test_append_to_note_is_medium():
    d = classify("append_to_note")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True


# ── Notes connector: surface guard ────────────────────────────────────────────

from app.connectors.notes import _is_blocked


def test_notes_blocked_password():
    assert _is_blocked("My Passwords") is True


def test_notes_blocked_credentials():
    assert _is_blocked("credentials backup") is True


def test_notes_blocked_ssh():
    assert _is_blocked("SSH keys 2024") is True


def test_notes_blocked_secret():
    assert _is_blocked("Secret tokens") is True


def test_notes_blocked_api_key():
    assert _is_blocked("api key list") is True


def test_notes_blocked_seed_phrase():
    assert _is_blocked("seed phrase backup") is True


def test_notes_blocked_bank():
    assert _is_blocked("bank account details") is True


def test_notes_blocked_ssn():
    assert _is_blocked("SSN and Tax Info") is True


def test_notes_blocked_private_key():
    assert _is_blocked("private key export") is True


def test_notes_blocked_token_plural():
    assert _is_blocked("tokens") is True


def test_notes_not_blocked_normal():
    assert _is_blocked("Meeting notes for Q1") is False


def test_notes_not_blocked_project():
    assert _is_blocked("Project planning") is False


def test_notes_not_blocked_recipe():
    assert _is_blocked("Pasta recipe") is False


def test_notes_not_blocked_empty():
    assert _is_blocked("") is False


def test_notes_blocked_case_insensitive():
    assert _is_blocked("PASSWORD VAULT") is True


def test_notes_blocked_partial_match():
    # "token" inside a longer word still matches
    assert _is_blocked("access tokenstore") is True


# ── Automator: run_shortcut name validation ────────────────────────────────────

from app.automator import run_shortcut


def test_run_shortcut_invalid_name_empty():
    result = run_shortcut("")
    assert result["success"] is False
    assert "Invalid shortcut name" in result["message"]


def test_run_shortcut_invalid_name_semicolon():
    result = run_shortcut("My; rm -rf /")
    assert result["success"] is False
    assert "Invalid shortcut name" in result["message"]


def test_run_shortcut_invalid_name_backtick():
    result = run_shortcut("`whoami`")
    assert result["success"] is False
    assert "Invalid shortcut name" in result["message"]


def test_run_shortcut_invalid_name_dollar():
    result = run_shortcut("$(evil)")
    assert result["success"] is False
    assert "Invalid shortcut name" in result["message"]


def test_run_shortcut_invalid_starts_with_space():
    result = run_shortcut(" Morning Routine")
    assert result["success"] is False


def test_run_shortcut_invalid_too_long():
    # 65 chars total — 1 leading + 64 more = fails (max 64 total)
    result = run_shortcut("A" + "b" * 64)
    assert result["success"] is False


# ── Automator: show_notification sanitization ──────────────────────────────────

import subprocess
from unittest.mock import patch, MagicMock

from app.automator import show_notification, set_volume, get_frontmost_app


def test_show_notification_truncates_long_message():
    long_msg = "x" * 300
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        show_notification(long_msg)
        call_args = mock_run.call_args[0][0]
        script = call_args[-1]
        # The embedded message must be ≤200 chars (plus surrounding quotes)
        assert long_msg[:201] not in script


def test_show_notification_escapes_quotes():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = show_notification('Say "hello"', title='Test')
        assert result["success"] is True
        call_args = mock_run.call_args[0][0]
        script = call_args[-1]
        # Unescaped quote would break AppleScript — must not appear unescaped
        assert 'Say "hello"' not in script  # raw unescaped form must be absent


def test_set_volume_clamps_above_10():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = set_volume(99)
        assert result["success"] is True
        call_args = mock_run.call_args[0][0]
        assert "10" in call_args[-1]


def test_set_volume_clamps_below_0():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = set_volume(-5)
        assert result["success"] is True
        call_args = mock_run.call_args[0][0]
        assert "0" in call_args[-1]


# ── Confidence: new actions have entries ───────────────────────────────────────

from app.confidence import compute_confidence


def test_confidence_set_volume_with_level():
    score = compute_confidence("set_volume", {"level": 5})
    assert score >= 0.80


def test_confidence_show_notification_with_message():
    score = compute_confidence("show_notification", {"message": "Hello world"})
    assert score >= 0.75


def test_confidence_run_shortcut_with_name():
    score = compute_confidence("run_shortcut", {"name": "Morning Routine"})
    assert score >= 0.70


def test_confidence_get_frontmost_app_no_params():
    score = compute_confidence("get_frontmost_app", {})
    assert score >= 0.85


def test_confidence_open_contacts_card_no_params():
    score = compute_confidence("open_contacts_card", {})
    assert score >= 0.80


def test_confidence_show_notification_missing_message():
    score = compute_confidence("show_notification", {})
    assert score < 0.80  # deducted for missing required param


def test_confidence_create_note_with_params():
    score = compute_confidence("create_note", {"title": "Meeting notes", "body": "Discussed Q2 roadmap"})
    assert score >= 0.60


def test_confidence_run_shortcut_missing_name():
    score = compute_confidence("run_shortcut", {})
    assert score < 0.70  # deducted for missing required param
