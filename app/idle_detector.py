"""
Idle detector — macOS only.
Reads HIDIdleTime from IOHIDSystem via ioreg. Value is in nanoseconds.
is_idle() returns True if the system has been idle for >= IDLE_THRESHOLD_SECONDS.
"""

import re
import subprocess

IDLE_THRESHOLD_SECONDS = 300  # 5 minutes


def get_idle_seconds() -> float:
    """
    Query macOS IOHIDSystem for the current HID idle time.
    Returns idle seconds as a float. Returns 0.0 on any error.
    """
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', result.stdout)
        if match:
            nanoseconds = int(match.group(1))
            return nanoseconds / 1_000_000_000
    except Exception:
        pass
    return 0.0


def is_idle() -> bool:
    """Return True if the system has been idle for >= 5 minutes."""
    return get_idle_seconds() >= IDLE_THRESHOLD_SECONDS
