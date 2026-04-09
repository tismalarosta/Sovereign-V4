"""
Charging gate — macOS only.
Reads power source from pmset -g batt.
is_charging() returns True if the Mac is on AC power.
"""

import subprocess


def is_charging() -> bool:
    """
    Return True if the Mac is connected to AC power.
    Parses 'pmset -g batt' output for 'AC Power'.
    Returns False on any error (fail-safe: don't index on unknown power state).
    """
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "AC Power" in result.stdout
    except Exception:
        return False
