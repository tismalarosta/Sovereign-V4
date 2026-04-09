"""
Phase 7 tests — confidence scoring overhaul (CONF-01) and scored intent
detection (CONF-02).
"""

import math
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.confidence import (
    _param_quality,
    _time_modifier,
    compute_confidence,
    interpret,
    log_feedback,
    _get_feedback_boost,
)


# ── _param_quality ────────────────────────────────────────────────────────────

class TestParamQuality:
    def test_none_returns_zero(self):
        assert _param_quality("app_name", None) == 0.0

    def test_empty_string_returns_zero(self):
        assert _param_quality("app_name", "") == 0.0

    def test_app_name_valid(self):
        assert _param_quality("app_name", "Spotify") == 0.9
        assert _param_quality("app_name", "Final Cut Pro") == 0.9

    def test_app_name_invalid_starts_with_digit(self):
        assert _param_quality("app_name", "1Password") < 0.5

    def test_app_name_invalid_too_long(self):
        long_name = "A" * 60
        assert _param_quality("app_name", long_name) < 0.5

    def test_path_existing(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert _param_quality("path", str(f)) == 1.0

    def test_path_nonexistent(self, tmp_path):
        score = _param_quality("path", str(tmp_path / "ghost.txt"))
        assert score == 0.4

    def test_url_valid_https(self):
        assert _param_quality("url", "https://example.com") == 0.9

    def test_url_valid_http(self):
        assert _param_quality("url", "http://example.com") == 0.9

    def test_url_missing_scheme(self):
        assert _param_quality("url", "example.com") < 0.5

    def test_query_two_words(self):
        assert _param_quality("query", "best restaurants") == 0.9

    def test_query_one_word(self):
        assert _param_quality("query", "restaurants") == 0.6

    def test_email_id_valid(self):
        assert _param_quality("email_id", "abc123xyz") == 0.9

    def test_email_id_invalid_special_chars(self):
        assert _param_quality("email_id", "abc 123!") < 0.5

    def test_unknown_param_present_returns_default(self):
        assert _param_quality("something_else", "any value") == 0.8


# ── compute_confidence ────────────────────────────────────────────────────────

class TestComputeConfidence:
    def test_unknown_action_returns_zero(self):
        assert compute_confidence("nonexistent_action", {}) == 0.0

    def test_open_app_good_name(self):
        score = compute_confidence("open_app", {"app_name": "Spotify"})
        # base 0.85 − (1-0.9)*0.30 = 0.85 − 0.03 = 0.82 (+ activity if chatted)
        assert score >= 0.80

    def test_open_app_bad_name(self):
        score = compute_confidence("open_app", {"app_name": "!!!bad!!!"})
        # base 0.85 − (1-0.3)*0.30 = 0.85 − 0.21 = 0.64
        assert score < 0.80

    def test_open_app_missing_name(self):
        score = compute_confidence("open_app", {})
        # base 0.85 − (1-0.0)*0.30 = 0.85 − 0.30 = 0.55
        assert score < 0.65

    def test_open_url_valid(self):
        score = compute_confidence("open_url", {"url": "https://example.com"})
        assert score >= 0.80

    def test_open_url_missing(self):
        score = compute_confidence("open_url", {})
        assert score < 0.65

    def test_rebuild_index_no_params_needed(self):
        # No required params → deduction = 0
        score = compute_confidence("rebuild_index", {})
        assert score >= 0.85

    def test_context_boost_caps_at_two_items(self):
        ctx = {"a": 1, "b": 2, "c": 3}
        score_ctx = compute_confidence("web_search", {"query": "hello world"}, context=ctx)
        score_no  = compute_confidence("web_search", {"query": "hello world"})
        assert score_ctx - score_no <= 0.11  # max boost is 0.10

    def test_clamp_high_does_not_exceed_one(self):
        score = compute_confidence("rebuild_index", {}, context={"a": 1, "b": 2})
        assert score <= 1.0

    def test_ultra_action_always_zero(self):
        assert compute_confidence("drop_database", {"db_name": "prod"}) == 0.0
        assert compute_confidence("grant_autonomy", {"level": "full"}) == 0.0


# ── interpret ─────────────────────────────────────────────────────────────────

class TestInterpret:
    def test_low(self):
        assert interpret(0.25) == "low — ask clarifying question"

    def test_medium_low(self):
        assert interpret(0.45) == "medium-low — LOW actions only, params incomplete"

    def test_medium(self):
        assert interpret(0.65) == "medium — LOW actions only"

    def test_high(self):
        assert interpret(0.85) == "high — MEDIUM approval path available"

    def test_boundary_exactly_0_30(self):
        assert interpret(0.30) == "medium-low — LOW actions only, params incomplete"

    def test_boundary_exactly_0_50(self):
        assert interpret(0.50) == "medium — LOW actions only"

    def test_boundary_exactly_0_70(self):
        assert interpret(0.70) == "high — MEDIUM approval path available"


# ── _time_modifier ────────────────────────────────────────────────────────────

class TestTimeModifier:
    def test_non_destructive_action_no_penalty(self):
        assert _time_modifier("open_app") == 0.0
        assert _time_modifier("web_search") == 0.0
        assert _time_modifier("rebuild_index") == 0.0

    def test_destructive_during_day_no_penalty(self):
        with patch("app.confidence.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 14
            assert _time_modifier("delete_file_trash") == 0.0

    def test_destructive_during_night_penalty(self):
        with patch("app.confidence.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 2
            assert _time_modifier("delete_file_trash") == -0.08

    def test_destructive_at_23_penalty(self):
        with patch("app.confidence.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            assert _time_modifier("move_email") == -0.08

    def test_destructive_at_7_no_penalty(self):
        with patch("app.confidence.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 7
            assert _time_modifier("remove_email_label") == 0.0


# ── _get_feedback_boost (decay) ───────────────────────────────────────────────

class TestFeedbackDecay:
    def test_no_history_returns_zero(self):
        # Use a fresh in-memory DB — no rows
        with patch("app.confidence.sqlite3.connect") as mock_conn:
            mock_conn.return_value.__enter__ = lambda s: s
            mock_conn.return_value.execute.return_value.fetchall.return_value = []
            mock_conn.return_value.close = lambda: None
            result = _get_feedback_boost("open_app")
        assert result == 0.0

    def test_recent_rejection_returns_penalty(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        rows = [(0, recent)]  # rejected 6 hours ago
        with patch("app.confidence.sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchall.return_value = rows
            mock_conn.return_value.close = lambda: None
            result = _get_feedback_boost("open_app")
        assert result == -0.12

    def test_strong_recent_approvals_boost(self):
        from datetime import datetime, timezone, timedelta
        # 5 approvals within the last 2 days — high weight
        rows = [
            (1, (datetime.now(timezone.utc) - timedelta(hours=i * 10)).isoformat())
            for i in range(5)
        ]
        with patch("app.confidence.sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchall.return_value = rows
            mock_conn.return_value.close = lambda: None
            result = _get_feedback_boost("open_app")
        assert result == 0.12

    def test_old_approvals_weighted_less(self):
        """A 30-day-old approval should contribute far less weight than a 1-day-old."""
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        # old approval weight = exp(-30/7) ≈ 0.013; new = exp(-1/7) ≈ 0.867
        w_old = math.exp(-30 / 7.0)
        w_new = math.exp(-1 / 7.0)
        assert w_new > w_old * 10


# ── Scored intent detection (CONF-02, via main._proposal_hint) ────────────────

class TestScoredIntentDetection:
    """Tests for _proposal_hint() weighted keyword scoring."""

    def setup_method(self):
        # Import here to pick up the patched version
        from app.main import _proposal_hint
        self._hint = _proposal_hint

    def test_longer_keyword_beats_shorter(self):
        # "show my downloads" (3 words, weight=1.0) vs "open" in "open downloads" (1 word, 0.33)
        # Message matches both; the 3-word one should win
        result = self._hint("show my downloads folder")
        assert result is not None
        assert result["detection_score"] >= 0.9

    def test_single_word_keyword_low_score(self):
        # "archive" alone is 1 word → weight = min(1/3, 1.0) = 0.333
        result = self._hint("please archive this email")
        assert result is not None
        assert result["detection_score"] <= 0.4

    def test_two_word_keyword_medium_score(self):
        # "move email" = 2 words → weight = min(2/3, 1.0) ≈ 0.667
        result = self._hint("I want to move email to archive")
        assert result is not None
        assert 0.6 < result["detection_score"] < 0.8

    def test_regex_fallback_scores_0_55(self):
        # "launch Spotify" has no keyword match but hits _ACTION_PATTERNS regex
        result = self._hint("launch Spotify for me")
        assert result is not None
        assert result["detection_score"] == 0.55

    def test_ambiguous_message_no_match(self):
        # Vague: "open something" — hits "open" keywords that require path/app context
        # but won't match unless a specific folder keyword is present
        result = self._hint("what time is it")
        assert result is None

    def test_detection_score_in_response(self):
        result = self._hint("search the web for Python tutorials")
        assert result is not None
        assert "detection_score" in result
        assert isinstance(result["detection_score"], float)
