"""
Phase 10 tests — OpenWeather + Philips Hue

Tests:
- Policy engine: all 5 Hue actions are LOW risk
- Hue connector: NOT_CONFIGURED when env vars empty, input clamping
- Weather connector: NOT_CONFIGURED when key empty
- Confidence: Hue action entries present
- Execution engine: Hue handlers wired

Run with: ./venv/bin/python -m pytest tests/test_phase10.py -v
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from unittest.mock import patch, MagicMock


# ── Policy engine: Hue actions are LOW ───────────────────────────────────────

from app.policy_engine import classify, RiskTier


def test_hue_turn_on_is_low():
    d = classify("hue_turn_on")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_hue_turn_off_is_low():
    d = classify("hue_turn_off")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_hue_set_brightness_is_low():
    d = classify("hue_set_brightness")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_hue_set_color_is_low():
    d = classify("hue_set_color")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


def test_hue_set_scene_is_low():
    d = classify("hue_set_scene")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True


# ── Hue connector: NOT_CONFIGURED when env vars empty ────────────────────────

from app.connectors import hue


def _patch_hue_unconfigured():
    """Context manager that patches settings to empty Hue config."""
    return patch.object(hue.settings, "hue_bridge_ip", ""), \
           patch.object(hue.settings, "hue_bridge_token", "")


def test_hue_turn_on_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.turn_on("1")
    assert result["success"] is False
    assert "not configured" in result["message"].lower()


def test_hue_turn_off_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.turn_off("1")
    assert result["success"] is False


def test_hue_set_brightness_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.set_brightness("1", 100)
    assert result["success"] is False


def test_hue_set_color_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.set_color("1", 10000, 200)
    assert result["success"] is False


def test_hue_set_scene_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.set_scene("abc")
    assert result["success"] is False


def test_hue_get_lights_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.get_lights()
    assert result["status"] == "NOT_CONFIGURED"


def test_hue_get_scenes_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.get_scenes()
    assert result["status"] == "NOT_CONFIGURED"


def test_hue_scan_not_configured():
    with patch.object(hue.settings, "hue_bridge_ip", ""), \
         patch.object(hue.settings, "hue_bridge_token", ""):
        result = hue.scan()
    assert result["status"] == "NOT_CONFIGURED"
    assert result["items_indexed"] == 0


# ── Hue connector: input clamping ────────────────────────────────────────────

def test_hue_set_brightness_clamps_above_254():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"), \
         patch("app.connectors.hue.httpx") as mock_httpx:
        mock_httpx.put.return_value = MagicMock(status_code=200)
        hue.set_brightness("1", 999)
        call_kwargs = mock_httpx.put.call_args
        sent_bri = call_kwargs[1]["json"]["bri"]
        assert sent_bri == 254


def test_hue_set_brightness_clamps_below_0():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"), \
         patch("app.connectors.hue.httpx") as mock_httpx:
        mock_httpx.put.return_value = MagicMock(status_code=200)
        hue.set_brightness("1", -50)
        call_kwargs = mock_httpx.put.call_args
        sent_bri = call_kwargs[1]["json"]["bri"]
        assert sent_bri == 0


def test_hue_set_color_clamps_hue():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"), \
         patch("app.connectors.hue.httpx") as mock_httpx:
        mock_httpx.put.return_value = MagicMock(status_code=200)
        hue.set_color("1", 99999, 300)
        call_kwargs = mock_httpx.put.call_args
        sent = call_kwargs[1]["json"]
        assert sent["hue"] == 65535
        assert sent["sat"] == 254


def test_hue_set_scene_empty_scene_id():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"):
        result = hue.set_scene("")
    assert result["success"] is False
    assert "scene_id" in result["message"]


def test_hue_turn_on_returns_undo_data():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"), \
         patch("app.connectors.hue.httpx") as mock_httpx:
        mock_httpx.put.return_value = MagicMock(status_code=200)
        result = hue.turn_on("2")
    assert result["success"] is True
    assert result["undo_data"]["action"] == "turn_off"
    assert result["undo_data"]["light_id"] == "2"


def test_hue_turn_off_returns_undo_data():
    with patch.object(hue.settings, "hue_bridge_ip", "192.168.1.1"), \
         patch.object(hue.settings, "hue_bridge_token", "testtoken"), \
         patch("app.connectors.hue.httpx") as mock_httpx:
        mock_httpx.put.return_value = MagicMock(status_code=200)
        result = hue.turn_off("3")
    assert result["success"] is True
    assert result["undo_data"]["action"] == "turn_on"
    assert result["undo_data"]["light_id"] == "3"


# ── Weather connector: NOT_CONFIGURED when key empty ─────────────────────────

from app.connectors import weather


def test_weather_not_configured():
    with patch.object(weather.settings, "openweather_key", ""):
        result = weather.fetch_weather()
    assert result["status"] == "NOT_CONFIGURED"
    assert "OPENWEATHER_KEY" in result["message"]


def test_weather_scan_not_configured():
    with patch.object(weather.settings, "openweather_key", ""):
        result = weather.scan()
    assert result["status"] == "NOT_CONFIGURED"
    assert result["items_indexed"] == 0


def test_weather_cache_used_when_fresh():
    """Second call within TTL should not make a new HTTP request."""
    import time
    fake_data = {
        "status": "OK", "city": "Paris", "lat": 48.86, "lon": 2.35,
        "current": {"temp": 18, "humidity": 60, "wind_speed": 10,
                    "description": "clear sky", "icon": "01d"},
        "daily": [],
    }
    weather._cache["data"] = fake_data
    weather._cache["fetched_at"] = time.time()  # just set

    with patch.object(weather.settings, "openweather_key", "testkey"), \
         patch("app.connectors.weather.httpx") as mock_http:
        result = weather.fetch_weather()

    # Cache hit — no HTTP call
    mock_http.get.assert_not_called()
    assert result["status"] == "OK"
    assert result["city"] == "Paris"

    # Clean up
    weather._cache.clear()


# ── Confidence: Hue entries present ──────────────────────────────────────────

from app.confidence import compute_confidence


def test_confidence_hue_turn_on_with_light_id():
    score = compute_confidence("hue_turn_on", {"light_id": "1"})
    assert score >= 0.80


def test_confidence_hue_turn_off_with_light_id():
    score = compute_confidence("hue_turn_off", {"light_id": "2"})
    assert score >= 0.80


def test_confidence_hue_set_brightness_full_params():
    score = compute_confidence("hue_set_brightness", {"light_id": "1", "brightness": 127})
    assert score >= 0.70


def test_confidence_hue_set_scene_with_id():
    score = compute_confidence("hue_set_scene", {"scene_id": "abcd1234"})
    assert score >= 0.75


def test_confidence_hue_turn_on_missing_light_id():
    score = compute_confidence("hue_turn_on", {})
    assert score < 0.85  # deducted for missing required param


def test_confidence_hue_set_brightness_missing_params():
    score = compute_confidence("hue_set_brightness", {})
    assert score < 0.75  # deducted for 2 missing required params
