"""
Contacts connector — reads Apple Contacts via osascript.
READ-ONLY. Indexes name, email, phone, company into ChromaDB.
Source prefix: contacts::

Gracefully skips if Contacts.app is not accessible or permission denied.
Never raises — always returns a status dict.
"""

import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "regis.db"

# AppleScript to export all contacts as tab-separated lines:
# name \t email \t phone \t company \n
_EXPORT_SCRIPT = """\
tell application "Contacts"
  set output to ""
  repeat with p in people
    set contactLine to (name of p) & "\\t"
    try
      set contactLine to contactLine & (value of email 1 of p) & "\\t"
    on error
      set contactLine to contactLine & "\\t"
    end try
    try
      set contactLine to contactLine & (value of phone 1 of p) & "\\t"
    on error
      set contactLine to contactLine & "\\t"
    end try
    try
      set contactLine to contactLine & (organization of p) & "\\t"
    on error
      set contactLine to contactLine & "\\t"
    end try
    set output to output & contactLine & "\\n"
  end repeat
  return output
end tell
"""

_NOT_CONFIGURED = {
    "connector": "contacts",
    "status": "NOT_CONFIGURED",
    "items_indexed": 0,
    "message": "Contacts.app not accessible or permission denied.",
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
        VALUES ('contacts', ?, ?, ?)
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
        "SELECT name, last_run, items_indexed, status FROM connectors WHERE name='contacts'"
    ).fetchone()
    conn.close()
    if row is None:
        return {"connector": "contacts", "status": "NOT_CONFIGURED", "items_indexed": 0, "last_run": None}
    return dict(row)


def scan() -> dict:
    """
    Read all Apple Contacts via osascript, embed, and upsert into ChromaDB.
    Gracefully skips on permission error or if Contacts not available.
    """
    try:
        from app.embeddings import embedder
        from app.chroma_store import store
    except ImportError as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "contacts", "status": "ERROR", "message": f"Import error: {exc}", "items_indexed": 0}

    try:
        result = subprocess.run(
            ["osascript", "-e", _EXPORT_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _upsert_status(0, "NOT_CONFIGURED")
            return {**_NOT_CONFIGURED, "message": result.stderr.strip() or "osascript failed"}

        raw = result.stdout.strip()
        if not raw:
            _upsert_status(0, "OK")
            return {"connector": "contacts", "status": "OK", "items_indexed": 0, "message": "No contacts found"}

        # Clear all existing contact chunks before re-indexing
        store.delete_by_filter({"source_type": {"$eq": "contacts"}})

        items_indexed = 0
        for line in raw.splitlines():
            parts = line.split("\t")
            name = parts[0].strip() if len(parts) > 0 else ""
            email = parts[1].strip() if len(parts) > 1 else ""
            phone = parts[2].strip() if len(parts) > 2 else ""
            company = parts[3].strip() if len(parts) > 3 else ""

            if not name:
                continue

            text = f"Contact: {name}"
            if email:
                text += f"\nEmail: {email}"
            if phone:
                text += f"\nPhone: {phone}"
            if company:
                text += f"\nCompany: {company}"

            source_key = f"contacts::{name}"
            chunk_id = f"contacts::{name}::0"

            try:
                emb = embedder.embed_one(text)
                store.upsert(
                    ids=[chunk_id],
                    embeddings=[emb],
                    documents=[text],
                    metadatas=[{
                        "source": source_key,
                        "source_type": "contacts",
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "company": company,
                    }],
                )
                items_indexed += 1
            except Exception:
                continue

        _upsert_status(items_indexed, "OK")
        return {"connector": "contacts", "status": "OK", "items_indexed": items_indexed}

    except subprocess.TimeoutExpired:
        _upsert_status(0, "ERROR")
        return {"connector": "contacts", "status": "ERROR", "message": "Contacts export timed out", "items_indexed": 0}
    except Exception as exc:
        _upsert_status(0, "ERROR")
        return {"connector": "contacts", "status": "ERROR", "message": str(exc), "items_indexed": 0}
