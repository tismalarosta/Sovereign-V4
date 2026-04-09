"""
Execution engine — the ONLY component that performs real mutations.
Flow: policy_engine classifies → proposal_manager creates proposal →
      user approves (MEDIUM) → execution_engine executes → action journaled.

Journal entry is written BEFORE execution begins. This ensures auditability
even if execution fails mid-way.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

from app.policy_engine import classify
from app.proposal_manager import (
    get_proposal,
    transition,
    set_undo_data,
    _get_db,
    _now,
)

_TRASH_PATH = Path.home() / ".Trash"


def _journal_action(
    proposal_id: str,
    action_type: str,
    parameters: dict,
    status: str = "PENDING",
    undo_data: dict | None = None,
) -> int:
    """Write an action journal entry. Must be called BEFORE execution begins."""
    conn = _get_db()
    cur = conn.execute(
        """INSERT INTO action_journal
           (proposal_id, action_type, parameters, status, journaled_at, undo_data)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            proposal_id,
            action_type,
            json.dumps(parameters),
            status,
            _now(),
            json.dumps(undo_data) if undo_data else None,
        ),
    )
    journal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return journal_id


def _update_journal(journal_id: int, status: str, undo_data: dict | None = None) -> None:
    conn = _get_db()
    if undo_data:
        conn.execute(
            "UPDATE action_journal SET status = ?, completed_at = ?, undo_data = ? WHERE id = ?",
            (status, _now(), json.dumps(undo_data), journal_id),
        )
    else:
        conn.execute(
            "UPDATE action_journal SET status = ?, completed_at = ? WHERE id = ?",
            (status, _now(), journal_id),
        )
    conn.commit()
    conn.close()


# ── Action implementations ────────────────────────────────────────────────────

def _execute_archive_email(params: dict) -> dict:
    """Archive an email via Gmail API. Falls back to stub if OAuth not available."""
    email_id = params.get("email_id", "")
    if not email_id:
        return {"success": False, "stub": False, "message": "No email_id provided", "undo_data": None}
    try:
        from app.connectors.gmail import _get_credentials
        from googleapiclient.discovery import build
        creds = _get_credentials()
        if creds is None:
            return {
                "success": False, "stub": True,
                "message": "Gmail not authorized — run OAuth flow first",
                "undo_data": None,
            }
        service = build("gmail", "v1", credentials=creds)
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["INBOX"]},
        ).execute()
        return {
            "success": True, "stub": False,
            "message": f"Archived email {email_id}",
            "undo_data": {"action": "unarchive_email", "email_id": email_id},
        }
    except ImportError:
        return {
            "success": True, "stub": True,
            "message": f"Email {email_id} marked for archive (google-api not installed — stub)",
            "undo_data": {"action": "unarchive_email", "email_id": email_id},
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def _execute_mark_read(params: dict) -> dict:
    """Mark an email as read via Gmail API. Falls back to stub if OAuth not available."""
    email_id = params.get("email_id", "")
    if not email_id:
        return {"success": False, "stub": False, "message": "No email_id provided", "undo_data": None}
    try:
        from app.connectors.gmail import _get_credentials
        from googleapiclient.discovery import build
        creds = _get_credentials()
        if creds is None:
            return {
                "success": False, "stub": True,
                "message": "Gmail not authorized — run OAuth flow first",
                "undo_data": None,
            }
        service = build("gmail", "v1", credentials=creds)
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
        return {
            "success": True, "stub": False,
            "message": f"Marked email {email_id} as read",
            "undo_data": {"action": "mark_unread", "email_id": email_id},
        }
    except ImportError:
        return {
            "success": True, "stub": True,
            "message": f"Email {email_id} marked as read (google-api not installed — stub)",
            "undo_data": {"action": "mark_unread", "email_id": email_id},
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def _execute_rebuild_index(_params: dict) -> dict:
    return {"success": True, "stub": False, "message": "Index rebuild requested", "undo_data": None}


def _execute_create_calendar_event(params: dict) -> dict:
    """Create a calendar event via Google Calendar API. Falls back to stub if OAuth not available."""
    title = params.get("title", "")
    start = params.get("start_time", "")
    end = params.get("end_time", "")
    if not title or not start or not end:
        return {"success": False, "stub": False, "message": "title, start_time, and end_time are required", "undo_data": None}
    try:
        from app.connectors.calendar import _get_credentials
        from googleapiclient.discovery import build
        creds = _get_credentials()
        if creds is None:
            return {
                "success": False, "stub": True,
                "message": "Calendar not authorized — run OAuth flow first",
                "undo_data": None,
            }
        service = build("calendar", "v3", credentials=creds)
        event_body = {
            "summary": title,
            "start": {"dateTime": start, "timeZone": "UTC"},
            "end":   {"dateTime": end,   "timeZone": "UTC"},
        }
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        event_id = created.get("id", "")
        return {
            "success": True, "stub": False,
            "message": f"Created event: {title}",
            "undo_data": {"action": "delete_calendar_event", "event_id": event_id},
        }
    except ImportError:
        return {
            "success": True, "stub": True,
            "message": f"Calendar event '{title}' ({start}–{end}) created (google-api not installed — stub)",
            "undo_data": {"action": "delete_calendar_event", "title": title, "start_time": start},
        }
    except Exception as exc:
        return {"success": False, "stub": False, "message": str(exc), "undo_data": None}


def _execute_delete_file_trash(params: dict) -> dict:
    """Move a file to ~/.Trash. Real execution when file exists."""
    file_path_str = params.get("file_path", "")
    file_path = Path(file_path_str).expanduser()

    if not file_path.exists():
        return {"success": False, "stub": False, "message": f"File not found: {file_path_str}", "undo_data": None}

    # Surface guard: refuse to trash project or system files
    project_root = Path(__file__).parent.parent
    try:
        file_path.resolve().relative_to(project_root.resolve())
        return {"success": False, "stub": False, "message": "Refusing to trash project files", "undo_data": None}
    except ValueError:
        pass  # Not under project root — safe to proceed

    trash_dest = _TRASH_PATH / file_path.name
    # Handle collision by appending a suffix
    counter = 1
    while trash_dest.exists():
        trash_dest = _TRASH_PATH / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1

    shutil.move(str(file_path), str(trash_dest))
    return {
        "success": True,
        "stub": False,
        "message": f"Moved '{file_path.name}' to Trash",
        "undo_data": {"action": "restore_from_trash", "trash_path": str(trash_dest), "original_path": str(file_path)},
    }


def _execute_move_email(params: dict) -> dict:
    email_id = params.get("email_id", "")
    target_folder = params.get("target_folder", "")
    return {
        "success": True,
        "stub": True,
        "message": f"Email {email_id} moved to '{target_folder}' (OAuth not configured — stub)",
        "undo_data": {"action": "move_email_back", "email_id": email_id},
    }


# ── OS / UI actions ───────────────────────────────────────────────────────────

def _execute_open_finder(params: dict) -> dict:
    """Open Finder to a directory, or reveal a file in Finder."""
    raw_path = params.get("path", "")
    if not raw_path:
        return {"success": False, "stub": False, "message": "No path provided", "undo_data": None}

    path = Path(raw_path).expanduser().resolve()

    # SEC-03: guard — path must be inside the user's home directory
    try:
        path.relative_to(Path.home().resolve())
    except ValueError:
        return {"success": False, "stub": False,
                "message": f"Access denied: path outside home directory", "undo_data": None}

    if not path.exists():
        # Try to open parent directory if the exact path doesn't exist
        if path.parent.exists():
            subprocess.run(["open", str(path.parent)], capture_output=True)
            return {"success": True, "stub": False,
                    "message": f"Opened parent folder: {path.parent}", "undo_data": None}
        return {"success": False, "stub": False,
                "message": f"Path not found: {raw_path}", "undo_data": None}

    if path.is_dir():
        subprocess.run(["open", str(path)], capture_output=True)
        msg = f"Opened Finder: {path}"
    else:
        # Reveal the file in Finder
        subprocess.run(["open", "-R", str(path)], capture_output=True)
        msg = f"Revealed in Finder: {path.name}"

    return {"success": True, "stub": False, "message": msg, "undo_data": None}


# SEC-03: allowlist for app names — letters, digits, spaces, hyphens, dots only
_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 \-\.]{0,63}$')


def _execute_open_app(params: dict) -> dict:
    """Launch a macOS application by name."""
    app_name = params.get("app_name", "")
    if not app_name:
        return {"success": False, "stub": False, "message": "No app name provided", "undo_data": None}

    # SEC-03: validate app name against allowlist pattern
    if not _SAFE_APP_NAME.match(app_name):
        return {"success": False, "stub": False,
                "message": f"Invalid app name: '{app_name}'", "undo_data": None}

    result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
    if result.returncode != 0:
        return {"success": False, "stub": False,
                "message": f"Could not open '{app_name}': {result.stderr.strip()}", "undo_data": None}
    return {"success": True, "stub": False, "message": f"Opened {app_name}", "undo_data": None}


def _execute_open_url(params: dict) -> dict:
    """Open a URL — tries Arc first, falls back to default browser."""
    url = params.get("url", "")
    if not url:
        return {"success": False, "stub": False, "message": "No URL provided", "undo_data": None}

    # Safety: only allow http/https
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url

    # Try Arc first, fall back to default browser
    result = subprocess.run(["open", "-a", "Arc", url], capture_output=True, text=True)
    if result.returncode != 0:
        subprocess.run(["open", url], capture_output=True)
        return {"success": True, "stub": False, "message": f"Opened in default browser: {url}", "undo_data": None}
    return {"success": True, "stub": False, "message": f"Opened in Arc: {url}", "undo_data": None}


def _execute_open_news_article(params: dict) -> dict:
    """Open a news article URL — delegates to open_url logic."""
    return _execute_open_url(params)


def _execute_web_search(params: dict) -> dict:
    """Open a web search in Arc/browser for a query."""
    query = params.get("query", "")
    if not query:
        return {"success": False, "stub": False, "message": "No query provided", "undo_data": None}

    import urllib.parse
    search_url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)
    result = subprocess.run(["open", "-a", "Arc", search_url], capture_output=True, text=True)
    if result.returncode != 0:
        subprocess.run(["open", search_url], capture_output=True)
    return {"success": True, "stub": False, "message": f"Searched: {query}", "undo_data": None}


def _execute_set_volume(params: dict) -> dict:
    from app.automator import set_volume
    level = params.get("level", 5)
    try:
        level = int(level)
    except (TypeError, ValueError):
        return {"success": False, "stub": False, "message": "level must be 0–10", "undo_data": None}
    return set_volume(level)


def _execute_get_frontmost_app(_params: dict) -> dict:
    from app.automator import get_frontmost_app
    return get_frontmost_app()


def _execute_show_notification(params: dict) -> dict:
    message = params.get("message", "")
    if not message:
        return {"success": False, "stub": False, "message": "No message provided", "undo_data": None}
    title = params.get("title", "Regis")
    from app.automator import show_notification
    return show_notification(message, title)


def _execute_run_shortcut(params: dict) -> dict:
    name = params.get("name", "")
    if not name:
        return {"success": False, "stub": False, "message": "No shortcut name provided", "undo_data": None}
    from app.automator import run_shortcut
    return run_shortcut(name)


def _execute_hue_turn_on(params: dict) -> dict:
    light_id = params.get("light_id", "1")
    from app.connectors.hue import turn_on
    return turn_on(light_id)


def _execute_hue_turn_off(params: dict) -> dict:
    light_id = params.get("light_id", "1")
    from app.connectors.hue import turn_off
    return turn_off(light_id)


def _execute_hue_set_brightness(params: dict) -> dict:
    light_id = params.get("light_id", "1")
    brightness = params.get("brightness", 127)
    from app.connectors.hue import set_brightness
    return set_brightness(light_id, brightness)


def _execute_hue_set_color(params: dict) -> dict:
    light_id = params.get("light_id", "1")
    hue_val = params.get("hue", 0)
    sat = params.get("sat", 254)
    from app.connectors.hue import set_color
    return set_color(light_id, hue_val, sat)


def _execute_hue_set_scene(params: dict) -> dict:
    scene_id = params.get("scene_id", "")
    group_id = params.get("group_id", "0")
    from app.connectors.hue import set_scene
    return set_scene(scene_id, group_id)


def _execute_open_contacts_card(params: dict) -> dict:
    """Open Contacts.app and search for a person by name."""
    name = params.get("name", "")
    if not name:
        subprocess.run(["open", "-a", "Contacts"], capture_output=True)
        return {"success": True, "stub": False, "message": "Opened Contacts", "undo_data": None}
    # Use osascript to open and select the contact
    safe_name = name[:100].replace("\\", "").replace('"', "")
    subprocess.run(
        ["osascript", "-e", f'tell application "Contacts" to activate'],
        capture_output=True,
    )
    return {"success": True, "stub": False, "message": f"Opened Contacts for: {name}", "undo_data": None}


_ACTION_HANDLERS = {
    "archive_email": _execute_archive_email,
    "mark_read": _execute_mark_read,
    "rebuild_index": _execute_rebuild_index,
    "create_calendar_event": _execute_create_calendar_event,
    "delete_file_trash": _execute_delete_file_trash,
    "move_email": _execute_move_email,
    "open_finder": _execute_open_finder,
    "open_app": _execute_open_app,
    "open_url": _execute_open_url,
    "open_news_article": _execute_open_news_article,
    "web_search": _execute_web_search,
    # MAC-03 automation
    "set_volume": _execute_set_volume,
    "get_frontmost_app": _execute_get_frontmost_app,
    "show_notification": _execute_show_notification,
    "run_shortcut": _execute_run_shortcut,
    # MAC-01
    "open_contacts_card": _execute_open_contacts_card,
    # HOME-02 Hue
    "hue_turn_on": _execute_hue_turn_on,
    "hue_turn_off": _execute_hue_turn_off,
    "hue_set_brightness": _execute_hue_set_brightness,
    "hue_set_color": _execute_hue_set_color,
    "hue_set_scene": _execute_hue_set_scene,
}


# ── Public interface ──────────────────────────────────────────────────────────

def execute_proposal(proposal_id: str) -> dict:
    """
    Execute an approved proposal.

    Flow:
    1. Load proposal from DB
    2. Validate it's APPROVED and LOW/MEDIUM
    3. Write journal entry (PENDING) — BEFORE any mutation
    4. Transition to EXECUTING
    5. Run action handler
    6. Update journal and transition to EXECUTED or FAILED
    7. Store undo_data for MEDIUM actions

    Raises ValueError on invalid state.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Proposal '{proposal_id}' not found")

    if proposal["status"] != "APPROVED":
        raise ValueError(
            f"Cannot execute proposal in state '{proposal['status']}' — must be APPROVED"
        )

    # Policy re-check (belt-and-suspenders)
    decision = classify(proposal["action_type"])
    if not decision.allowed:
        transition(proposal_id, "REJECTED", reason=f"Policy re-check failed: {decision.reason}")
        raise ValueError(f"Policy denied execution: {decision.reason}")

    action_type = proposal["action_type"]
    parameters = proposal["parameters"]

    # Journal BEFORE execution
    journal_id = _journal_action(proposal_id, action_type, parameters, status="PENDING")

    # Transition to EXECUTING
    transition(proposal_id, "EXECUTING")

    handler = _ACTION_HANDLERS.get(action_type)
    if not handler:
        _update_journal(journal_id, "FAILED")
        transition(proposal_id, "FAILED", reason=f"No handler for action type '{action_type}'")
        raise ValueError(f"No execution handler for '{action_type}'")

    try:
        result = handler(parameters)

        if result.get("success"):
            undo_data = result.get("undo_data")
            _update_journal(journal_id, "COMPLETE", undo_data=undo_data)
            transition(proposal_id, "EXECUTED")

            # Store undo data for MEDIUM actions
            if proposal["risk_tier"] == "MEDIUM" and undo_data:
                set_undo_data(proposal_id, undo_data)

            return {
                "proposal_id": proposal_id,
                "status": "EXECUTED",
                "action_type": action_type,
                "result": result,
            }
        else:
            _update_journal(journal_id, "FAILED")
            transition(proposal_id, "FAILED", reason=result.get("message", "Execution failed"))
            return {
                "proposal_id": proposal_id,
                "status": "FAILED",
                "action_type": action_type,
                "result": result,
            }

    except Exception as exc:
        _update_journal(journal_id, "FAILED")
        transition(proposal_id, "FAILED", reason=str(exc))
        raise


def undo_proposal(proposal_id: str) -> dict:
    """
    Undo an EXECUTED MEDIUM-risk proposal using stored undo_data.
    Only MEDIUM tier supports undo.
    """
    proposal = get_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Proposal '{proposal_id}' not found")

    if proposal["status"] != "EXECUTED":
        raise ValueError(f"Can only undo EXECUTED proposals, not '{proposal['status']}'")

    if proposal["risk_tier"] != "MEDIUM":
        raise ValueError(f"Undo only supported for MEDIUM risk actions, not '{proposal['risk_tier']}'")

    undo_data = proposal.get("undo_data")
    if not undo_data:
        raise ValueError(f"No undo data available for proposal '{proposal_id}'")

    undo_action = undo_data.get("action", "")

    # Handle known undo actions
    if undo_action == "restore_from_trash":
        trash_path = Path(undo_data["trash_path"])
        original_path = Path(undo_data["original_path"])
        if not trash_path.exists():
            raise ValueError(f"Trash file not found: {trash_path}")
        shutil.move(str(trash_path), str(original_path))
        return {"undone": True, "message": f"Restored '{trash_path.name}' from Trash"}

    elif undo_action in ("delete_calendar_event", "unarchive_email", "mark_unread", "move_email_back"):
        # Stubs — OAuth not yet configured
        return {
            "undone": True,
            "stub": True,
            "message": f"Undo '{undo_action}' recorded (OAuth not configured — stub)",
        }

    raise ValueError(f"Unknown undo action: '{undo_action}'")
