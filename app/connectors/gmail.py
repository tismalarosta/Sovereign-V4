"""
Gmail connector — single authority for Gmail ingestion.
Read-only. Uses OAuth2. Skips gracefully if credentials not configured.
Token stored at data/gmail_token.json. Credentials at data/gmail_creds.json.
See docs/task_updates/2026-03-31_gmail-setup.md for setup instructions.
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "regis.db"
CREDS_PATH = Path(__file__).parent.parent.parent / "data" / ".secrets" / "gmail_creds.json"
TOKEN_PATH = Path(__file__).parent.parent.parent / "data" / ".secrets" / "gmail_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_NOT_CONFIGURED = {
    "connector": "gmail",
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
        VALUES ('gmail', ?, ?, ?)
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
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json())
            return creds
        except Exception:
            return None

    return None  # Need interactive OAuth flow — not possible in server context


# ── Public API ────────────────────────────────────────────────────────────────

def get_status() -> dict:
    """Return current status from the connectors table."""
    conn = _get_db()
    row = conn.execute(
        "SELECT name, last_run, items_indexed, status FROM connectors WHERE name='gmail'"
    ).fetchone()
    conn.close()
    if row is None:
        return {"connector": "gmail", "status": "NOT_CONFIGURED", "items_indexed": 0, "last_run": None}
    return dict(row)


def scan() -> dict:
    """
    Scan last 30 days of Gmail (inbox + sent). Read-only.
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
        return {"connector": "gmail", "status": "ERROR", "message": f"Import error: {exc}", "items_indexed": 0}

    creds = _get_credentials()
    if creds is None:
        _upsert_status(0, "NOT_CONFIGURED")
        return {
            "connector": "gmail",
            "status": "NOT_CONFIGURED",
            "items_indexed": 0,
            "message": "Run OAuth flow first. See docs/task_updates/2026-03-31_gmail-setup.md",
        }

    try:
        service = build("gmail", "v1", credentials=creds)

        # Paginate through ALL messages — no date filter
        messages = []
        page_token = None
        while True:
            kwargs = {"userId": "me", "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            result = service.users().messages().list(**kwargs).execute()
            messages.extend(result.get("messages", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        items_indexed = 0
        for msg_ref in messages:
            msg_id = msg_ref["id"]
            source_key = f"gmail::{msg_id}"

            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="metadata",
                    metadataHeaders=["Subject", "From", "Date"],
                ).execute()

                headers = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                subject = headers.get("Subject", "(no subject)")[:200]
                sender = headers.get("From", "unknown")[:200]
                date_str = headers.get("Date", "")[:100]
                snippet = msg.get("snippet", "")[:500]

                text = f"Subject: {subject}\nFrom: {sender}\nDate: {date_str}\n\n{snippet}"
                emb = embedder.embed_one(text)
                chunk_id = f"gmail::{msg_id}::0"
                metadata = {
                    "source": source_key,
                    "source_type": "gmail",
                    "message_id": msg_id,
                    "subject": subject,
                    "sender": sender,
                    "date": date_str,
                }
                store.upsert(
                    ids=[chunk_id],
                    embeddings=[emb],
                    documents=[text],
                    metadatas=[metadata],
                )
                items_indexed += 1
            except Exception:
                continue  # skip individual message errors silently

        _upsert_status(items_indexed, "OK")
        return {"connector": "gmail", "status": "OK", "items_indexed": items_indexed}

    except Exception as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "gmail", "status": "ERROR", "message": str(exc), "items_indexed": 0}
