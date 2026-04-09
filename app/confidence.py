"""
Confidence scorer — computes 0.0–1.0 confidence for proposed actions.
Combines deterministic base scoring with adaptive learning from user feedback.
Confidence is a property of the action + context, NOT of the policy tier.

Phase 7 upgrades:
- Parameter quality scoring (not just binary present/missing)
- Exponential decay on feedback (half-life ~5 days)
- Time-of-day modifier (penalizes destructive actions at night)
- Session activity boost (user is present if chatted in last 10 min)
- 4-tier interpret() instead of 3
"""

import math
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"

# Required parameters per action type.
_REQUIRED_PARAMS: dict[str, list[str]] = {
    "archive_email": ["email_id"],
    "mark_read": ["email_id"],
    "add_metadata_tag": ["target", "tag"],
    "rebuild_index": [],
    "clean_temp_files": [],
    "rerun_index": [],
    "open_finder": ["path"],
    "open_app": ["app_name"],
    "open_url": ["url"],
    "web_search": ["query"],
    "move_email": ["email_id", "target_folder"],
    "remove_email_label": ["email_id", "label"],
    "create_calendar_event": ["title", "start_time", "end_time"],
    "update_calendar_event": ["event_id"],
    "delete_file_trash": ["file_path"],
    "draft_reply": ["email_id", "body"],
    "transfer_money": ["amount", "recipient"],
    "submit_tax_form": ["form_id"],
    "send_legal_email": ["recipient", "subject", "body"],
    "delete_permanent": ["target"],
    "change_security_settings": ["setting", "value"],
    # INFO-01 News
    "open_news_article": ["url"],
    # HOME-02 Hue actions
    "hue_turn_on": ["light_id"],
    "hue_turn_off": ["light_id"],
    "hue_set_brightness": ["light_id", "brightness"],
    "hue_set_color": ["light_id", "hue", "sat"],
    "hue_set_scene": ["scene_id"],
    # MAC-01–03 actions
    "open_contacts_card": [],
    "set_volume": ["level"],
    "get_frontmost_app": [],
    "show_notification": ["message"],
    "run_shortcut": ["name"],
    "create_note": ["title", "body"],
    "append_to_note": ["title", "body"],
    # ULTRA
    "access_keychain": ["key_name"],
    "exfiltrate_credentials": ["target"],
    "modify_etc": ["file_path"],
    "drop_database": ["db_name"],
    "modify_policy_engine": [],
    "grant_autonomy": ["level"],
    "self_modify_governance": ["document"],
}

# Base confidence scores per action type (before param/context/feedback checks).
_BASE_CONFIDENCE: dict[str, float] = {
    "archive_email": 0.80,
    "mark_read": 0.85,
    "add_metadata_tag": 0.75,
    "rebuild_index": 0.90,
    "clean_temp_files": 0.85,
    "rerun_index": 0.90,
    "open_finder": 0.88,
    "open_app": 0.85,
    "open_url": 0.85,
    "web_search": 0.80,
    "move_email": 0.75,
    "remove_email_label": 0.75,
    "create_calendar_event": 0.75,
    "update_calendar_event": 0.70,
    "delete_file_trash": 0.72,
    "draft_reply": 0.70,
    # INFO-01 News
    "open_news_article": 0.90,
    # HOME-02 Hue actions
    "hue_turn_on": 0.88,
    "hue_turn_off": 0.88,
    "hue_set_brightness": 0.85,
    "hue_set_color": 0.82,
    "hue_set_scene": 0.85,
    # MAC-01–03 actions
    "open_contacts_card": 0.88,
    "set_volume": 0.90,
    "get_frontmost_app": 0.92,
    "show_notification": 0.85,
    "run_shortcut": 0.78,
    "create_note": 0.75,
    "append_to_note": 0.75,
    # HIGH and ULTRA have 0.0 base — blocked regardless
    "transfer_money": 0.0,
    "submit_tax_form": 0.0,
    "send_legal_email": 0.0,
    "delete_permanent": 0.0,
    "change_security_settings": 0.0,
    "access_keychain": 0.0,
    "exfiltrate_credentials": 0.0,
    "modify_etc": 0.0,
    "drop_database": 0.0,
    "modify_policy_engine": 0.0,
    "grant_autonomy": 0.0,
    "self_modify_governance": 0.0,
}

# Actions penalized during sleep hours (23:00–06:59 local time).
_DESTRUCTIVE_ACTIONS: set[str] = {"delete_file_trash", "move_email", "remove_email_label"}

# Regex for validating identifiers (email IDs, event IDs).
_ID_RE = re.compile(r'^[A-Za-z0-9_\-\.@]+$')
# Regex for validating app names (must start with a letter).
_APP_NAME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9 ]{0,40}$')


# ── Parameter quality scoring ─────────────────────────────────────────────────

def _param_quality(param: str, value) -> float:
    """
    Return a quality score in [0.0, 1.0] for a parameter value.
    0.0 = missing; 1.0 = perfectly validated.
    """
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0

    if param == "app_name":
        return 0.9 if _APP_NAME_RE.match(s) else 0.3
    if param == "path":
        return 1.0 if Path(s).expanduser().exists() else 0.4
    if param == "url":
        return 0.9 if re.match(r'^https?://', s) else 0.3
    if param == "query":
        return 0.9 if len(s.split()) >= 2 else 0.6
    if param in ("email_id", "event_id"):
        return 0.9 if _ID_RE.match(s) else 0.4
    # All other params: present = 0.8
    return 0.8


# ── Exponential-decay feedback boost ─────────────────────────────────────────

def _get_feedback_boost(action_type: str) -> float:
    """
    Return a confidence adjustment based on time-weighted approval history.

    Uses exponential decay with half-life ~5 days (exp(-days/7)).
    - Recent rejection (≤3 days) → −0.12 (overrides everything)
    - weighted_rate ≥ 0.90 and total_weight ≥ 2 → +0.12
    - weighted_rate ≥ 0.75 and total_weight ≥ 1 → +0.07
    - Insufficient data → 0.0
    """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        since_60d = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        rows = conn.execute(
            "SELECT approved, created_at FROM feedback_log "
            "WHERE action_type = ? AND created_at >= ?",
            (action_type, since_60d),
        ).fetchall()
        conn.close()

        if not rows:
            return 0.0

        now = datetime.now(timezone.utc)
        total_weight = 0.0
        weighted_approvals = 0.0
        recent_rejection = False

        for approved_int, created_at_str in rows:
            ts = datetime.fromisoformat(created_at_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            days_ago = (now - ts).total_seconds() / 86400.0
            w = math.exp(-days_ago / 7.0)
            total_weight += w
            if approved_int:
                weighted_approvals += w
            elif days_ago <= 3:
                recent_rejection = True

        if recent_rejection:
            return -0.12

        if total_weight == 0:
            return 0.0

        rate = weighted_approvals / total_weight
        if total_weight >= 2 and rate >= 0.90:
            return 0.12
        if total_weight >= 1 and rate >= 0.75:
            return 0.07
        return 0.0
    except Exception:
        return 0.0


# ── Time-of-day modifier ──────────────────────────────────────────────────────

def _time_modifier(action_type: str) -> float:
    """Penalize destructive actions during sleep hours (23:00–06:59 local)."""
    if action_type not in _DESTRUCTIVE_ACTIONS:
        return 0.0
    hour = datetime.now().hour  # local time, intentionally
    if hour >= 23 or hour < 7:
        return -0.08
    return 0.0


# ── Session activity boost ────────────────────────────────────────────────────

def _activity_boost() -> float:
    """Return +0.05 if the user sent a chat message in the last 10 minutes."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT created_at FROM chat_messages ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            ts = datetime.fromisoformat(row[0])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - ts).total_seconds() < 600:
                return 0.05
    except Exception:
        pass
    return 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def log_feedback(action_type: str, approved: bool) -> None:
    """Record a user approval or rejection to the feedback_log table."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute(
            "INSERT INTO feedback_log (action_type, approved, created_at) VALUES (?, ?, ?)",
            (action_type, 1 if approved else 0, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Non-fatal — feedback is best-effort


def compute_confidence(
    action_type: str,
    parameters: dict,
    context: dict | None = None,
) -> float:
    """
    Compute confidence score for a proposed action.

    Algorithm:
    1. Unknown action type → 0.0
    2. Start from base score
    3. Parameter quality deduction: sum((1 - quality) * 0.30) per required param
    4. Context boost: +0.05 per context item, max +0.10
    5. Exponential-decay feedback boost/penalty
    6. Time-of-day modifier (destructive actions penalized at night)
    7. Session activity boost (+0.05 if user active in last 10 min)
    8. Clamp to [0.0, 1.0]
    """
    if action_type not in _BASE_CONFIDENCE:
        return 0.0

    base     = _BASE_CONFIDENCE[action_type]
    required = _REQUIRED_PARAMS.get(action_type, [])

    deduction = sum(
        (1.0 - _param_quality(p, parameters.get(p))) * 0.30
        for p in required
    )

    context_boost = 0.0
    if context:
        context_items = len([v for v in context.values() if v])
        context_boost = min(context_items * 0.05, 0.10)

    feedback_boost = _get_feedback_boost(action_type)
    time_mod       = _time_modifier(action_type)
    activity       = _activity_boost()

    score = base - deduction + context_boost + feedback_boost + time_mod + activity
    return round(max(0.0, min(1.0, score)), 3)


def interpret(score: float) -> str:
    """Human-readable interpretation of a confidence score (4 tiers)."""
    if score < 0.30:
        return "low — ask clarifying question"
    if score < 0.50:
        return "medium-low — LOW actions only, params incomplete"
    if score < 0.70:
        return "medium — LOW actions only"
    return "high — MEDIUM approval path available"
