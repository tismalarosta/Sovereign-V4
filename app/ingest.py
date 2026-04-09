"""
Ingest authority — scans docs/ folder, chunks .md files, embeds and stores.
Only reads from docs/ (Phase 1 scope). No other paths allowed.
"""

import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from app.embeddings import embedder
from app.chroma_store import store

DOCS_PATH = Path(__file__).parent.parent / "docs"
DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"

CHUNK_SIZE = 400       # characters per chunk
CHUNK_OVERLAP = 80     # overlap between chunks


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end].strip())
        start += size - overlap
    return [c for c in chunks if c]


def _chunk_id(source: str, idx: int, text: str) -> str:
    """Deterministic chunk ID from source path, index, and content hash."""
    h = hashlib.sha1(text.encode()).hexdigest()[:8]
    return f"{source}::{idx}::{h}"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create scan_history and connectors tables if they don't exist."""
    conn = _get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            chunks_stored INTEGER NOT NULL,
            scanned_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS connectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            last_run TEXT,
            items_indexed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'NOT_CONFIGURED'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            action_type TEXT NOT NULL,
            parameters TEXT NOT NULL,
            risk_tier TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            rejection_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            executed_at TEXT,
            undo_data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS action_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            parameters TEXT NOT NULL,
            status TEXT NOT NULL,
            journaled_at TEXT NOT NULL,
            completed_at TEXT,
            undo_data TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            approved INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS suggestions_cache (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            subtitle TEXT,
            text TEXT NOT NULL,
            source TEXT,
            generated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def scan_docs() -> dict:
    """
    Scan all .md files in docs/, chunk, embed, and upsert into ChromaDB.
    Records each file in scan_history. Idempotent.
    Returns summary dict.
    """
    init_db()
    md_files = sorted(DOCS_PATH.glob("*.md"))
    if not md_files:
        return {"files_scanned": 0, "chunks_stored": 0, "files": []}

    results = []
    total_chunks = 0

    for md_file in md_files:
        source = md_file.name
        text = md_file.read_text(encoding="utf-8")
        chunks = _chunk_text(text)

        ids = [_chunk_id(source, i, c) for i, c in enumerate(chunks)]
        embeddings = embedder.embed(chunks)
        metadatas = [{"source": source, "chunk_index": i} for i in range(len(chunks))]

        # Remove old chunks for this source before re-ingesting
        store.delete_by_source(source)
        store.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metadatas)

        # Log to scan_history
        conn = _get_db()
        conn.execute(
            "INSERT INTO scan_history (source, chunks_stored, scanned_at) VALUES (?, ?, ?)",
            (source, len(chunks), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

        total_chunks += len(chunks)
        results.append({"file": source, "chunks": len(chunks)})

    return {
        "files_scanned": len(md_files),
        "chunks_stored": total_chunks,
        "files": results,
    }


def get_scan_history() -> list[dict]:
    """Return most recent scan per source file."""
    init_db()
    conn = _get_db()
    rows = conn.execute("""
        SELECT source, chunks_stored, scanned_at
        FROM scan_history
        ORDER BY scanned_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
