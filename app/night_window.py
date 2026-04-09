"""
Night window — returns True if current local time is between 23:00 and 06:00.
This is the window when proactive background indexing is allowed.
"""

from datetime import datetime


def in_night_window() -> bool:
    """
    Return True if local time is in the night indexing window: 23:00–06:00.
    Safe to call at any time — never raises.
    """
    hour = datetime.now().hour
    return 2 <= hour < 7
