"""
Proposal manager — manages the proposal lifecycle in SQLite.
States: PROPOSED → APPROVED → EXECUTING → EXECUTED / FAILED / REJECTED
ULTRA proposals are immediately REJECTED on creation. No override.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"

VALID_TRANSITIONS: dict[str, list[str]] = {
    "PROPOSED": ["APPROVED", "REJECTED"],
    "APPROVED": ["EXECUTING", "REJECTED"],
    "EXECUTING": ["EXECUTED", "FAILED"],
    "EXECUTED": [],    # terminal
    "FAILED": [],      # terminal
    "REJECTED": [],    # terminal
}


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_proposals_db() -> None:
    """Create proposals and action_journal tables if they don't exist."""
    conn = _get_db()
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
    conn.commit()
    conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_proposal(
    action_type: str,
    parameters: dict,
    risk_tier: str,
    confidence: float,
    rejection_reason: str | None = None,
) -> dict:
    """
    Create a new proposal in SQLite. ULTRA proposals are immediately REJECTED.
    Returns the created proposal as a dict.
    """
    proposal_id = str(uuid.uuid4())
    now = _now()

    # ULTRA = immediate rejection, no override
    if risk_tier == "ULTRA":
        status = "REJECTED"
        rejection_reason = rejection_reason or f"ULTRA risk tier — hard deny, no override"
    elif risk_tier == "HIGH":
        status = "REJECTED"
        rejection_reason = rejection_reason or f"HIGH risk tier — draft only, no auto-execution"
    elif confidence < 0.30:
        status = "REJECTED"
        rejection_reason = f"Confidence {confidence:.3f} < 0.30 — ask clarifying question instead"
    else:
        status = "PROPOSED"

    conn = _get_db()
    conn.execute(
        """INSERT INTO proposals (id, action_type, parameters, risk_tier, confidence,
           status, rejection_reason, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            proposal_id,
            action_type,
            json.dumps(parameters),
            risk_tier,
            confidence,
            status,
            rejection_reason,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()

    result = get_proposal(proposal_id)
    if result is None:
        raise RuntimeError(f"Proposal '{proposal_id}' missing after insert")
    return result


def get_proposal(proposal_id: str) -> dict | None:
    """Retrieve a single proposal by ID."""
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    p = dict(row)
    p["parameters"] = json.loads(p["parameters"])
    if p["undo_data"]:
        p["undo_data"] = json.loads(p["undo_data"])
    return p


def list_proposals(status: str | None = None) -> list[dict]:
    """List all proposals, optionally filtered by status."""
    conn = _get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM proposals ORDER BY created_at DESC"
        ).fetchall()
    conn.close()

    results = []
    for row in rows:
        p = dict(row)
        p["parameters"] = json.loads(p["parameters"])
        if p["undo_data"]:
            p["undo_data"] = json.loads(p["undo_data"])
        results.append(p)
    return results


def transition(proposal_id: str, new_status: str, reason: str | None = None) -> dict:
    """
    Transition a proposal to a new status. Validates the transition is legal.
    Raises ValueError on invalid transition.
    All transitions are logged before execution.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Proposal '{proposal_id}' not found")

    current = proposal["status"]
    allowed = VALID_TRANSITIONS.get(current, [])

    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition: {current} → {new_status}. "
            f"Allowed from {current}: {allowed}"
        )

    # Double-check: ULTRA/HIGH cannot be approved (belt-and-suspenders)
    if new_status == "APPROVED" and proposal["risk_tier"] in ("ULTRA", "HIGH"):
        raise ValueError(
            f"Cannot approve {proposal['risk_tier']} risk proposals — hard deny"
        )

    now = _now()
    conn = _get_db()

    update_fields = "status = ?, updated_at = ?"
    params: list = [new_status, now]

    if new_status in ("EXECUTED",):
        update_fields += ", executed_at = ?"
        params.append(now)

    if new_status in ("REJECTED", "FAILED") and reason:
        update_fields += ", rejection_reason = ?"
        params.append(reason)

    params.append(proposal_id)
    conn.execute(f"UPDATE proposals SET {update_fields} WHERE id = ?", params)
    conn.commit()
    conn.close()

    result = get_proposal(proposal_id)
    if result is None:
        raise RuntimeError(f"Proposal '{proposal_id}' missing after transition")
    return result


def set_undo_data(proposal_id: str, undo_data: dict) -> None:
    """Store undo data for a proposal (MEDIUM risk actions)."""
    conn = _get_db()
    conn.execute(
        "UPDATE proposals SET undo_data = ? WHERE id = ?",
        (json.dumps(undo_data), proposal_id),
    )
    conn.commit()
    conn.close()
