"""
Weather connector — server-side OpenWeather One Call 3.0 API.
Caches response in memory (TTL 30 min). Indexes daily forecast into ChromaDB.
Source prefix: weather::

Gracefully returns NOT_CONFIGURED if OPENWEATHER_KEY is empty.
Never raises — always returns a status dict.
"""

import time
from datetime import datetime

import httpx

from app.settings import settings

_cache: dict = {}   # {"data": dict, "fetched_at": float}
CACHE_TTL = 1800    # 30 minutes


def _get_location() -> tuple[float, float, str]:
    """IP-based geolocation — same approach as the former client-side call."""
    r = httpx.get("https://ipapi.co/json/", timeout=5)
    d = r.json()
    return d.get("latitude", 48.86), d.get("longitude", 2.35), d.get("city", "")


def fetch_weather() -> dict:
    """
    Fetch current conditions + 7-day forecast from OpenWeather.
    Returns cached result if age < CACHE_TTL.
    Returns {"status": "NOT_CONFIGURED"} if key is absent.
    """
    if not settings.openweather_key:
        return {
            "status": "NOT_CONFIGURED",
            "message": "OPENWEATHER_KEY not set in data/.env",
        }

    now = time.time()
    if _cache.get("data") and (now - _cache.get("fetched_at", 0)) < CACHE_TTL:
        return _cache["data"]

    try:
        lat, lon, city = _get_location()
    except Exception:
        lat, lon, city = 48.86, 2.35, ""

    try:
        r = httpx.get(
            "https://api.openweathermap.org/data/3.0/onecall",
            params={
                "lat": lat,
                "lon": lon,
                "appid": settings.openweather_key,
                "units": "metric",
                "exclude": "minutely,alerts",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as exc:
        return {
            "status": "ERROR",
            "message": f"OpenWeather API error: {exc.response.status_code}",
        }
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc)}

    result: dict = {
        "status": "OK",
        "city": city,
        "lat": lat,
        "lon": lon,
        "current": {
            "temp": round(data["current"]["temp"]),
            "humidity": data["current"]["humidity"],
            "wind_speed": round(data["current"].get("wind_speed", 0)),
            "description": data["current"]["weather"][0]["description"],
            "icon": data["current"]["weather"][0]["icon"],
        },
        "daily": [
            {
                "date": d["dt"],
                "temp_min": round(d["temp"]["min"]),
                "temp_max": round(d["temp"]["max"]),
                "description": d["weather"][0]["description"],
                "icon": d["weather"][0]["icon"],
                "pop": round(d.get("pop", 0) * 100),   # precipitation %
            }
            for d in data.get("daily", [])[:7]
        ],
    }

    _cache["data"] = result
    _cache["fetched_at"] = now
    return result


def scan() -> dict:
    """
    Index daily weather forecast into ChromaDB for chat context.
    Runs as part of the background connector scan loop.
    """
    try:
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        return {
            "connector": "weather",
            "status": "ERROR",
            "items_indexed": 0,
            "message": f"Import error: {exc}",
        }

    weather = fetch_weather()
    if weather.get("status") != "OK":
        return {
            "connector": "weather",
            "status": weather["status"],
            "items_indexed": 0,
            "message": weather.get("message", ""),
        }

    store.delete_by_filter({"source_type": {"$eq": "weather"}})

    items = 0
    for day in weather.get("daily", []):
        dt = datetime.utcfromtimestamp(day["date"])
        date_str = dt.strftime("%A %B %d")
        text = (
            f"Weather forecast for {date_str}: "
            f"{day['description']}, {day['temp_min']}–{day['temp_max']}°C, "
            f"precipitation chance {day['pop']}%"
        )
        chunk_id = f"weather::{dt.strftime('%Y-%m-%d')}"
        try:
            emb = embedder.embed_one(text)
            store.upsert(
                ids=[chunk_id],
                embeddings=[emb],
                documents=[text],
                metadatas=[{
                    "source": chunk_id,
                    "source_type": "weather",
                    "date": dt.strftime("%Y-%m-%d"),
                }],
            )
            items += 1
        except Exception:
            continue

    return {"connector": "weather", "status": "OK", "items_indexed": items}
