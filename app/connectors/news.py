"""
News connector — NewsAPI.org top headlines.
Caches response in memory (TTL 2 hours). Indexes headlines into ChromaDB.
Source prefix: news::

Gracefully returns NOT_CONFIGURED if NEWS_API_KEY is empty.
Filters tabloid and misinformation domains before indexing.
Never raises — always returns a status dict.
"""

import hashlib
import time
from urllib.parse import urlparse

import httpx

from app.settings import settings

_cache: dict = {}   # {"data": dict, "fetched_at": float}
CACHE_TTL = 7200    # 2 hours

_BLOCKED_DOMAINS = frozenset({
    "dailymail.co.uk",
    "thesun.co.uk",
    "nypost.com",
    "rt.com",
    "sputniknews.com",
    "breitbart.com",
    "infowars.com",
    "naturalnews.com",
    "zerohedge.com",
})


def _domain(url: str) -> str:
    """Extract base domain from a URL."""
    try:
        return urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""


def _is_blocked(article: dict) -> bool:
    """True if the article's source domain is on the blocklist."""
    url = article.get("url", "")
    return _domain(url) in _BLOCKED_DOMAINS


def fetch_headlines() -> dict:
    """
    Fetch top headlines from NewsAPI.
    Returns cached result if age < CACHE_TTL.
    Returns {"status": "NOT_CONFIGURED"} if key is absent.
    """
    if not settings.news_api_key:
        return {
            "status": "NOT_CONFIGURED",
            "message": "NEWS_API_KEY not set in data/.env",
        }

    now = time.time()
    if _cache.get("data") and (now - _cache.get("fetched_at", 0)) < CACHE_TTL:
        return _cache["data"]

    try:
        r = httpx.get(
            "https://newsapi.org/v2/top-headlines",
            params={
                "apiKey": settings.news_api_key,
                "language": "en",
                "pageSize": 20,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as exc:
        return {
            "status": "ERROR",
            "message": f"NewsAPI error: {exc.response.status_code}",
        }
    except Exception as exc:
        return {"status": "ERROR", "message": str(exc)}

    articles = [a for a in data.get("articles", []) if not _is_blocked(a)]

    result: dict = {
        "status": "OK",
        "total_results": data.get("totalResults", 0),
        "articles": [
            {
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "url": a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
            }
            for a in articles
            if a.get("title") and a.get("url")
        ],
    }

    _cache["data"] = result
    _cache["fetched_at"] = now
    return result


def scan() -> dict:
    """
    Index top headlines into ChromaDB for chat context.
    Runs as part of the background connector scan loop (once daily in night window).
    """
    try:
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        return {
            "connector": "news",
            "status": "ERROR",
            "items_indexed": 0,
            "message": f"Import error: {exc}",
        }

    headlines = fetch_headlines()
    if headlines.get("status") != "OK":
        return {
            "connector": "news",
            "status": headlines["status"],
            "items_indexed": 0,
            "message": headlines.get("message", ""),
        }

    store.delete_by_filter({"source_type": {"$eq": "news"}})

    items = 0
    for article in headlines.get("articles", []):
        title = article.get("title", "").strip()
        description = article.get("description", "").strip()
        source_name = article.get("source", "").strip()
        url = article.get("url", "").strip()
        published_at = article.get("published_at", "").strip()

        if not title or not url:
            continue

        text = f"[{source_name}] {title}"
        if description:
            text += f". {description}"

        title_hash = hashlib.sha1(title.encode()).hexdigest()[:10]
        date_prefix = published_at[:10] if published_at else "unknown"
        chunk_id = f"news::{date_prefix}::{title_hash}"

        try:
            emb = embedder.embed_one(text)
            store.upsert(
                ids=[chunk_id],
                embeddings=[emb],
                documents=[text],
                metadatas=[{
                    "source": chunk_id,
                    "source_type": "news",
                    "url": url,
                    "published_at": published_at,
                    "source_name": source_name,
                }],
            )
            items += 1
        except Exception:
            continue

    return {"connector": "news", "status": "OK", "items_indexed": items}
