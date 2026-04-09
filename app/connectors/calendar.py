"""
Calendar connector — single authority for Google Calendar ingestion.
Read-only. Reuses OAuth credentials from Gmail connector.
Scans past 7 days + next 30 days. Skips gracefully if not configured.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "regis.db"

# Reuse Gmail OAuth credentials if available
CREDS_PATH = Path(__file__).parent.parent.parent / "data" / ".secrets" / "gmail_creds.json"
TOKEN_PATH = Path(__file__).parent.parent.parent / "data" / ".secrets" / "gmail_token.json"

_NOT_CONFIGURED = {
    "connector": "calendar",
    "status": "NOT_CONFIGURED",
    "items_indexed": 0,
    "message": "OAuth credentials not found. See docs/task_updates/2026-03-31_gmail-setup.md",
}


# ── DB helpers ────────────────────────────────────────────────────────────────

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
        VALUES ('calendar', ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            last_run=excluded.last_run,
            items_indexed=excluded.items_indexed,
            status=excluded.status
        """,
        (now, items_indexed, status),
    )
    conn.commit()
    conn.close()


# ── OAuth helper ──────────────────────────────────────────────────────────────

def _get_credentials():
    """Return valid credentials or None if OAuth not set up."""
    from app.connectors.gmail import _get_credentials as gmail_creds
    return gmail_creds()


# ── Public API ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current status from the connectors table."""
    conn = _get_db()
    row = conn.execute(
        "SELECT name, last_run, items_indexed, status FROM connectors WHERE name='calendar'"
    ).fetchone()
    conn.close()
    if row is None:
        return {"connector": "calendar", "status": "NOT_CONFIGURED", "items_indexed": 0, "last_run": None}
    return dict(row)


def scan() -> dict:
    """
    Scan Google Calendar events: past 7 days + next 30 days.
    Skips gracefully if OAuth not configured. Never raises.
    """
    if not CREDS_PATH.exists():
        _upsert_status(0, "NOT_CONFIGURED")
        return _NOT_CONFIGURED

    try:
        from googleapiclient.discovery import build
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "calendar", "status": "ERROR", "message": f"Import error: {exc}", "items_indexed": 0}

    creds = _get_credentials()
    if creds is None:
        _upsert_status(0, "NOT_CONFIGURED")
        return {
            "connector": "calendar",
            "status": "NOT_CONFIGURED",
            "items_indexed": 0,
            "message": "Run OAuth flow first. See docs/task_updates/2026-03-31_gmail-setup.md",
        }

    try:
        service = build("calendar", "v3", credentials=creds)

        now = datetime.now(timezone.utc)
        # Only keep a rolling window: past 30 days + next 90 days
        time_min = (now - timedelta(days=30)).isoformat()
        time_max = (now + timedelta(days=90)).isoformat()

        # Wipe all existing calendar chunks and re-index fresh window.
        # This clears out old events (e.g. 2010–2025) on every scan.
        store.delete_by_filter({"source_type": {"$eq": "calendar"}})

        # Paginate through events in the rolling window
        events = []
        page_token = None
        while True:
            kwargs = {
                "calendarId": "primary",
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": 2500,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.events().list(**kwargs).execute()
            events.extend(result.get("items", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        items_indexed = 0

        for event in events:
            event_id = event.get("id", "")
            source_key = f"calendar::{event_id}"

            try:
                title = event.get("summary", "(no title)")[:200]
                description = (event.get("description") or "")[:500]
                start = event.get("start", {})
                start_str = start.get("dateTime") or start.get("date") or ""
                end = event.get("end", {})
                end_str = end.get("dateTime") or end.get("date") or ""
                attendees_raw = event.get("attendees", [])
                attendees = ", ".join(
                    a.get("email", "") for a in attendees_raw if a.get("email")
                )[:300]

                text = (
                    f"Event: {title}\n"
                    f"Start: {start_str}\n"
                    f"End: {end_str}\n"
                    f"Attendees: {attendees}\n\n"
                    f"{description}"
                ).strip()

                emb = embedder.embed_one(text)
                chunk_id = f"calendar::{event_id}::0"
                metadata = {
                    "source": source_key,
                    "source_type": "calendar",
                    "event_id": event_id,
                    "title": title,
                    "start": start_str,
                    "end": end_str,
                }
                store.upsert(
                    ids=[chunk_id],
                    embeddings=[emb],
                    documents=[text],
                    metadatas=[metadata],
                )
                items_indexed += 1
            except Exception:
                continue

        _upsert_status(items_indexed, "OK")
        return {"connector": "calendar", "status": "OK", "items_indexed": items_indexed}

    except Exception as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "calendar", "status": "ERROR", "message": str(exc), "items_indexed": 0}
