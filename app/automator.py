"""
macOS Automator — allowlisted osascript/Shortcuts actions.
ALL osascript calls use a fixed template string — no arbitrary script execution.
This module is the ONLY place macOS system automation is performed.

Allowed actions (enforced by the allowlist in execution_engine.py via policy_engine.py):
  set_volume          LOW  — set system volume 0-10
  get_frontmost_app   LOW  — return name of frontmost app (read-only)
  show_notification   LOW  — display macOS Notification Center alert
  run_shortcut        MEDIUM — trigger a named macOS Shortcut
"""

import re
import subprocess

# Regex for safe shortcut names: letters, digits, spaces, hyphens only
_SHORTCUT_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 \-]{0,63}$')


def set_volume(level: int) -> dict:
    """Set system volume to 0–10. Clamps input to valid range."""
    level = max(0, min(10, int(level)))
    subprocess.run(
        ["osascript", "-e", f"set volume {level}"],
        capture_output=True,
        timeout=5,
    )
    return {"success": True, "stub": False, "message": f"Volume set to {level}", "undo_data": None}


def get_frontmost_app() -> dict:
    """Return the name of the current frontmost application (read-only)."""
    r = subprocess.run(
        [
            "osascript", "-e",
            'tell application "System Events" to get name of first process whose frontmost is true',
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    app_name = r.stdout.strip()
    return {"success": True, "stub": False, "message": app_name or "unknown", "undo_data": None}


def show_notification(message: str, title: str = "Regis") -> dict:
    """Display a macOS Notification Center alert. Input is sanitised before embedding."""
    # Sanitise: cap length, escape quotes (AppleScript string injection guard)
    msg = message[:200].replace("\\", "\\\\").replace('"', '\\"')
    ttl = title[:50].replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        [
            "osascript", "-e",
            f'display notification "{msg}" with title "{ttl}"',
        ],
        capture_output=True,
        timeout=5,
    )
    return {"success": True, "stub": False, "message": "Notification shown", "undo_data": None}


def run_shortcut(name: str) -> dict:
    """
    Trigger a named macOS Shortcut.
    Name must match ^[A-Za-z0-9][A-Za-z0-9 \\-]{0,63}$ — no arbitrary strings.
    """
    if not _SHORTCUT_NAME_RE.match(name):
        return {
            "success": False,
            "stub": False,
            "message": f"Invalid shortcut name: '{name}'. Only letters, digits, spaces, hyphens allowed.",
            "undo_data": None,
        }
    try:
        r = subprocess.run(
            ["shortcuts", "run", name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return {"success": True, "stub": False, "message": f"Shortcut '{name}' executed", "undo_data": None}
        return {
            "success": False,
            "stub": False,
            "message": r.stderr.strip() or f"Shortcut '{name}' failed (exit {r.returncode})",
            "undo_data": None,
        }
    except FileNotFoundError:
        return {"success": False, "stub": False, "message": "'shortcuts' CLI not found — requires macOS 12+", "undo_data": None}
    except subprocess.TimeoutExpired:
        return {"success": False, "stub": False, "message": f"Shortcut '{name}' timed out after 30s", "undo_data": None}
