"""
Snapshot authority — generates the system state dict from lifecycle only.
UI reads ONLY from /snapshot. This module is the single source of truth.
"""

import sqlite3
import time
from pathlib import Path

from app.lifecycle import lifecycle

DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"


def _connector_summary() -> list[dict]:
    """Read connector statuses from DB. Returns empty list if table not ready."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, last_run, items_indexed, status FROM connectors"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def build_snapshot() -> dict:
    """Return a valid JSON-serializable snapshot of current system state."""
    state = lifecycle.state
    started_at = lifecycle.started_at
    state_changed_at = lifecycle.state_changed_at

    uptime_seconds: float | None = None
    if started_at is not None and state.value == "ACTIVE":
        uptime_seconds = round(time.time() - started_at, 1)

    return {
        "state": state.value,
        "uptime_seconds": uptime_seconds,
        "state_changed_at": round(state_changed_at, 3),
        "snapshot_at": round(time.time(), 3),
        "connectors": _connector_summary(),
    }
