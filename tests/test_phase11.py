"""
Phase 11 tests — NewsAPI connector (INFO-01)

Tests:
- Policy: open_news_article is LOW risk
- Confidence: entry exists with base >= 0.85
- news.py NOT_CONFIGURED when key empty
- news.py scan NOT_CONFIGURED when key empty
- Blocked domain filtering
- Cache TTL hit
- _source_type("news::...") returns "news"
- _CONNECTORS has "news" key
- Execution handler wired

Run with: ./venv/bin/python -m pytest tests/test_phase11.py -v
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

import time
from unittest.mock import patch, MagicMock


# ── Policy ────────────────────────────────────────────────────────────────────

from app.policy_engine import classify, RiskTier


def test_open_news_article_is_low():
    d = classify("open_news_article")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


# ── Confidence ────────────────────────────────────────────────────────────────

from app.confidence import compute_confidence, _REQUIRED_PARAMS, _BASE_CONFIDENCE


def test_news_required_params_entry():
    assert "open_news_article" in _REQUIRED_PARAMS
    assert "url" in _REQUIRED_PARAMS["open_news_article"]


def test_news_base_confidence_entry():
    assert "open_news_article" in _BASE_CONFIDENCE
    assert _BASE_CONFIDENCE["open_news_article"] >= 0.85


def test_news_confidence_with_url():
    conf = compute_confidence("open_news_article", {"url": "https://example.com/article"})
    assert conf >= 0.80


# ── news.py NOT_CONFIGURED ────────────────────────────────────────────────────

def test_news_fetch_not_configured():
    with patch("app.connectors.news.settings") as mock_settings:
        mock_settings.news_api_key = ""
        from app.connectors.news import fetch_headlines
        result = fetch_headlines()
    assert result["status"] == "NOT_CONFIGURED"


def test_news_scan_not_configured():
    with patch("app.connectors.news.settings") as mock_settings:
        mock_settings.news_api_key = ""
        from app.connectors.news import scan
        result = scan()
    assert result["status"] == "NOT_CONFIGURED"
    assert result["connector"] == "news"
    assert result["items_indexed"] == 0


# ── Blocked domain filtering ──────────────────────────────────────────────────

def test_blocked_domain_filtered():
    from app.connectors.news import _is_blocked
    assert _is_blocked({"url": "https://www.dailymail.co.uk/article/123"}) is True
    assert _is_blocked({"url": "https://rt.com/news/whatever"}) is True
    assert _is_blocked({"url": "https://breitbart.com/politics/2026"}) is True


def test_allowed_domain_not_filtered():
    from app.connectors.news import _is_blocked
    assert _is_blocked({"url": "https://www.bbc.com/news/article"}) is False
    assert _is_blocked({"url": "https://reuters.com/world"}) is False
    assert _is_blocked({"url": "https://apnews.com/article"}) is False


def test_blocked_articles_excluded_from_fetch():
    """Blocked domains should not appear in the fetch_headlines result."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "status": "ok",
        "totalResults": 2,
        "articles": [
            {
                "title": "Good article",
                "description": "From a real source",
                "source": {"name": "BBC"},
                "url": "https://www.bbc.com/news/good",
                "publishedAt": "2026-04-09T10:00:00Z",
            },
            {
                "title": "Tabloid trash",
                "description": "Clickbait",
                "source": {"name": "Daily Mail"},
                "url": "https://www.dailymail.co.uk/trash/123",
                "publishedAt": "2026-04-09T10:00:00Z",
            },
        ],
    }

    import app.connectors.news as news_mod
    # Clear cache so fetch runs
    news_mod._cache.clear()

    with patch("app.connectors.news.settings") as mock_settings, \
         patch("app.connectors.news.httpx.get", return_value=mock_response):
        mock_settings.news_api_key = "test_key"
        result = news_mod.fetch_headlines()

    assert result["status"] == "OK"
    urls = [a["url"] for a in result["articles"]]
    assert "https://www.bbc.com/news/good" in urls
    assert "https://www.dailymail.co.uk/trash/123" not in urls


# ── Cache TTL ─────────────────────────────────────────────────────────────────

def test_news_cache_hit():
    """Second call within TTL returns cached data without hitting API."""
    import app.connectors.news as news_mod

    cached_data = {"status": "OK", "articles": [], "total_results": 0}
    news_mod._cache["data"] = cached_data
    news_mod._cache["fetched_at"] = time.time()  # just now

    call_count = {"n": 0}

    def fake_get(*_a, **_kw):
        call_count["n"] += 1
        return MagicMock()

    with patch("app.connectors.news.settings") as mock_settings, \
         patch("app.connectors.news.httpx.get", side_effect=fake_get):
        mock_settings.news_api_key = "key"
        result = news_mod.fetch_headlines()

    assert call_count["n"] == 0   # no HTTP call made
    assert result is cached_data


# ── main.py integration ───────────────────────────────────────────────────────

def test_source_type_news():
    """_source_type should return 'news' for news:: prefixed sources."""
    from pathlib import Path
    import re
    source = Path(__file__).parent.parent / "app" / "main.py"
    text = source.read_text()
    assert 'source.startswith("news::"): return "news"' in text


def test_connectors_dict_has_news():
    """_CONNECTORS in main.py must include 'news'."""
    from pathlib import Path
    text = (Path(__file__).parent.parent / "app" / "main.py").read_text()
    assert '"news": news_connector' in text


def test_news_endpoint_defined():
    """GET /news endpoint must be defined in main.py."""
    from pathlib import Path
    text = (Path(__file__).parent.parent / "app" / "main.py").read_text()
    assert '@app.get("/news"' in text


# ── Execution handler ─────────────────────────────────────────────────────────

def test_open_news_article_handler_wired():
    """open_news_article handler must be in _ACTION_HANDLERS."""
    from app.execution_engine import _ACTION_HANDLERS
    assert "open_news_article" in _ACTION_HANDLERS


def test_open_news_article_no_url_fails_gracefully():
    """open_news_article with no URL should return success=False without crashing."""
    from app.execution_engine import _ACTION_HANDLERS
    handler = _ACTION_HANDLERS["open_news_article"]
    result = handler({})
    assert result["success"] is False
