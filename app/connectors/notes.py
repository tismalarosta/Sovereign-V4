"""
Notes connector — reads Apple Notes via AppleScript.
READ-ONLY. Indexes note title + body into ChromaDB.
Source prefix: notes::

SURFACE GUARD: notes whose titles contain sensitive keywords are never indexed.
This is non-negotiable and cannot be overridden.

Gracefully skips if Notes.app is not accessible or permission denied.
"""

import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "regis.db"

# Notes with titles containing any of these keywords are NEVER indexed.
# Case-insensitive substring match.
_BLOCKED_TITLE_KEYWORDS: frozenset[str] = frozenset({
    "password", "passwords", "credential", "credentials",
    "ssh", "secret", "secrets", "private key", "private_key",
    "token", "tokens", "api key", "api_key",
    "seed phrase", "recovery", "mnemonic",
    "bank account", "credit card", "ssn", "social security",
})

CHUNK_SIZE = 400
CHUNK_OVERLAP = 80

# AppleScript: export all notes as title + body separated by markers
_EXPORT_SCRIPT = """\
tell application "Notes"
  set output to ""
  repeat with n in notes
    set t to name of n
    set b to plaintext of n
    set output to output & "===TITLE===" & t & "===BODY===" & b & "===END===\\n"
  end repeat
  return output
end tell
"""

_NOT_CONFIGURED = {
    "connector": "notes",
    "status": "NOT_CONFIGURED",
    "items_indexed": 0,
    "message": "Notes.app not accessible or permission denied.",
}


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _upsert_status(items_indexed: int, status: str) -> None:
    conn = _get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO connectors (name, last_run, items_indexed, status)
        VALUES ('notes', ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run=excluded.last_run,
            items_indexed=excluded.items_indexed,
            status=excluded.status
        """,
        (now, items_indexed, status),
    )
    conn.commit()
    conn.close()


def get_status() -> dict:
    conn = _get_db()
    row = conn.execute(
        "SELECT name, last_run, items_indexed, status FROM connectors WHERE name='notes'"
    ).fetchone()
    conn.close()
    if row is None:
        return {"connector": "notes", "status": "NOT_CONFIGURED", "items_indexed": 0, "last_run": None}
    return dict(row)


def _is_blocked(title: str) -> bool:
    """Return True if this note's title matches any sensitive keyword."""
    t = title.lower()
    return any(kw in t for kw in _BLOCKED_TITLE_KEYWORDS)


def _chunk_text(text: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE].strip())
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c]


def scan() -> dict:
    """
    Read all Apple Notes via osascript, embed, and upsert into ChromaDB.
    Sensitive notes are silently skipped (not logged — just not indexed).
    """
    try:
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "notes", "status": "ERROR", "message": f"Import error: {exc}", "items_indexed": 0}

    try:
        result = subprocess.run(
            ["osascript", "-e", _EXPORT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            _upsert_status(0, "NOT_CONFIGURED")
            return {**_NOT_CONFIGURED, "message": result.stderr.strip() or "osascript failed"}

        raw = result.stdout.strip()
        if not raw:
            _upsert_status(0, "OK")
            return {"connector": "notes", "status": "OK", "items_indexed": 0, "message": "No notes found"}

        # Parse notes from the marker-delimited output
        notes_raw = raw.split("===END===")
        notes: list[tuple[str, str]] = []
        for entry in notes_raw:
            entry = entry.strip()
            if "===TITLE===" not in entry or "===BODY===" not in entry:
                continue
            after_title = entry.split("===TITLE===", 1)[1]
            parts = after_title.split("===BODY===", 1)
            title = parts[0].strip()
            body  = parts[1].strip() if len(parts) > 1 else ""
            if title:
                notes.append((title, body))

        # Clear existing notes chunks before re-indexing
        store.delete_by_filter({"source_type": {"$eq": "notes"}})

        items_indexed = 0
        blocked_count = 0

        for title, body in notes:
            if _is_blocked(title):
                blocked_count += 1
                continue  # silently skip — never log sensitive content

            source_key = f"notes::{title}"
            full_text = f"Note: {title}\n\n{body}"
            chunks = _chunk_text(full_text)

            for i, chunk in enumerate(chunks):
                chunk_id = f"notes::{title}::{i}"
                try:
                    emb = embedder.embed_one(chunk)
                    store.upsert(
                        ids=[chunk_id],
                        embeddings=[emb],
                        documents=[chunk],
                        metadatas=[{
                            "source": source_key,
                            "source_type": "notes",
                            "title": title[:200],
                            "chunk_index": i,
                        }],
                    )
                except Exception:
                    continue

            items_indexed += 1

        _upsert_status(items_indexed, "OK")
        return {
            "connector": "notes",
            "status": "OK",
            "items_indexed": items_indexed,
            "blocked": blocked_count,
        }

    except subprocess.TimeoutExpired:
        _upsert_status(0, "ERROR")
        return {"connector": "notes", "status": "ERROR", "message": "Notes export timed out", "items_indexed": 0}
    except Exception as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "notes", "status": "ERROR", "message": str(exc), "items_indexed": 0}
