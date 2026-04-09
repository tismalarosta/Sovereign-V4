"""
Suggestion engine — Phase 8.

Generates LLM-powered smart suggestions during free time (idle + battery_ok +
in_night_window preferred). Results cached in SQLite suggestions_cache table.
Cache TTL: 8 hours.

The /suggestions endpoint reads from this cache — it never blocks on generation.
Generation runs in the background indexer thread via maybe_refresh().

Public API:
    get_cached()         — read from cache, returns [] if cold or stale
    maybe_refresh()      — trigger generation if cache is stale; non-blocking
    force_refresh()      — unconditional regeneration (for manual trigger)
"""

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"
CACHE_TTL_HOURS = 8

# LLM prompt for suggestion generation
_PROMPT_TEMPLATE = """\
You are Regis, a personal AI assistant. Based on the following snippets from the user's \
files, emails, and calendar, suggest 3 to 5 short, natural questions the user might want \
to ask you right now. Each question should be actionable and specific to the content shown.

Context snippets:
{context}

Respond with ONLY a JSON array of strings, like:
["What does the meeting with Alice cover?", "Summarize my latest email from Bob", ...]
Do not include any explanation or markdown."""


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _cache_age_hours() -> float | None:
    """Return age of the most recent cache entry in hours, or None if empty."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT generated_at FROM suggestions_cache ORDER BY generated_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return None
        ts = datetime.fromisoformat(row["generated_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 3600
    except Exception:
        return None


def get_cached() -> list[dict]:
    """
    Return cached suggestions if they're fresher than CACHE_TTL_HOURS.
    Returns [] if cache is cold, stale, or DB unavailable.
    """
    age = _cache_age_hours()
    if age is None or age >= CACHE_TTL_HOURS:
        return []
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, type, title, subtitle, text, source FROM suggestions_cache "
            "ORDER BY generated_at DESC LIMIT 6"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _generate_and_cache() -> None:
    """
    Query ChromaDB for recent context, ask LLM for suggestions,
    parse the response, and upsert into suggestions_cache.

    Only runs if Ollama is reachable. Silently exits on any error.
    """
    try:
        import httpx
        # Quick reachability check — don't attempt generation if LLM is offline
        try:
            httpx.get("http://127.0.0.1:11434/api/tags", timeout=1)
        except Exception:
            logger.debug("Suggestion engine: LLM offline, skipping generation")
            return

        from app.chroma_store import store
        from app.embeddings import embedder
        from app.ollama_client import generate_stream

        # Gather context: upcoming calendar + recent files + recent emails
        context_parts: list[str] = []

        try:
            from datetime import date
            today = date.today().isoformat()
            cal_chunks = store.get_where({"source_type": {"$eq": "calendar"}}, limit=100)
            upcoming = sorted(
                [c for c in cal_chunks if c.get("start", "") >= today],
                key=lambda c: c.get("start", ""),
            )[:3]
            for c in upcoming:
                context_parts.append(f"[Calendar] {c.get('document', '')[:200]}")
        except Exception:
            pass

        try:
            file_hits = store.query(
                embedder.embed_one("recent important document notes"),
                n_results=4,
                where={"source_type": {"$eq": "file"}},
            )
            for h in file_hits[:3]:
                context_parts.append(f"[File] {h['document'][:200]}")
        except Exception:
            pass

        try:
            email_hits = store.query(
                embedder.embed_one("urgent email unread reply"),
                n_results=4,
                where={"source_type": {"$eq": "gmail"}},
            )
            for h in email_hits[:3]:
                context_parts.append(f"[Email] {h['document'][:200]}")
        except Exception:
            pass

        if not context_parts:
            logger.debug("Suggestion engine: no context available, skipping generation")
            return

        prompt = _PROMPT_TEMPLATE.format(context="\n\n".join(context_parts))

        # Collect the full LLM response (non-streaming collect)
        response_text = ""
        for token in generate_stream(prompt):
            response_text += token
            if len(response_text) > 2000:
                break

        # Parse JSON array from response
        # Find the first '[' and last ']' to be robust against surrounding text
        start = response_text.find("[")
        end = response_text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            logger.warning("Suggestion engine: could not parse LLM response as JSON array")
            return

        suggestions_raw: list = json.loads(response_text[start : end + 1])
        if not isinstance(suggestions_raw, list):
            return

        now = datetime.now(timezone.utc).isoformat()
        conn = _get_db()
        # Clear old cache before inserting fresh suggestions
        conn.execute("DELETE FROM suggestions_cache")
        for i, text in enumerate(suggestions_raw[:6]):
            if not isinstance(text, str) or not text.strip():
                continue
            sid = hashlib.sha1(f"{now}:{i}:{text}".encode()).hexdigest()[:16]
            conn.execute(
                """INSERT OR REPLACE INTO suggestions_cache
                   (id, type, title, subtitle, text, source, generated_at)
                   VALUES (?, 'ai', ?, NULL, ?, NULL, ?)""",
                (sid, text.strip()[:80], text.strip(), now),
            )
        conn.commit()
        conn.close()
        logger.info("Suggestion engine: generated %d suggestions", min(len(suggestions_raw), 6))

    except Exception as exc:
        logger.warning("Suggestion engine: generation failed: %s", exc)


def maybe_refresh(force: bool = False) -> None:
    """
    Trigger generation if cache is stale (≥ CACHE_TTL_HOURS old) or forced.
    Always non-blocking — runs synchronously inside the background indexer thread
    which is already at nice +19.
    """
    if not force:
        age = _cache_age_hours()
        if age is not None and age < CACHE_TTL_HOURS:
            return  # cache is fresh
    _generate_and_cache()


def force_refresh() -> None:
    """Unconditional cache regeneration. For manual trigger via endpoint."""
    _generate_and_cache()
