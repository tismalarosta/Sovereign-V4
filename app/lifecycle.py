"""
Lifecycle state machine — the single authority for system state.
All state transitions must go through this module.
"""

from enum import Enum
from threading import Lock
import time


class LifecycleState(str, Enum):
    OFFLINE = "OFFLINE"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


# Valid transitions: from_state -> set of allowed to_states
_VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.OFFLINE:   {LifecycleState.STARTING},
    LifecycleState.STARTING:  {LifecycleState.ACTIVE, LifecycleState.ERROR},
    LifecycleState.ACTIVE:    {LifecycleState.PAUSED, LifecycleState.STOPPING, LifecycleState.ERROR},
    LifecycleState.PAUSED:    {LifecycleState.ACTIVE, LifecycleState.STOPPING, LifecycleState.ERROR},
    LifecycleState.STOPPING:  {LifecycleState.OFFLINE, LifecycleState.ERROR},
    LifecycleState.ERROR:     {LifecycleState.OFFLINE},
}


class Lifecycle:
    def __init__(self) -> None:
        self._state = LifecycleState.OFFLINE
        self._lock = Lock()
        self._started_at: float | None = None
        self._state_changed_at: float = time.time()

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def started_at(self) -> float | None:
        return self._started_at

    @property
    def state_changed_at(self) -> float:
        return self._state_changed_at

    def transition(self, target: LifecycleState) -> bool:
        """Attempt a state transition. Returns True if successful, False if invalid."""
        with self._lock:
            allowed = _VALID_TRANSITIONS.get(self._state, set())
            if target not in allowed:
                return False
            self._state = target
            self._state_changed_at = time.time()
            if target == LifecycleState.ACTIVE and self._started_at is None:
                self._started_at = time.time()
            return True

    def start(self) -> dict:
        """Idempotent start: OFFLINE→STARTING→ACTIVE."""
        if self._state == LifecycleState.ACTIVE:
            return {"ok": True, "state": self._state, "note": "already active"}
        if self._state not in (LifecycleState.OFFLINE, LifecycleState.ERROR):
            return {"ok": False, "state": self._state, "note": "invalid state for start"}
        # OFFLINE or ERROR → reset to OFFLINE first if ERROR
        if self._state == LifecycleState.ERROR:
            self.transition(LifecycleState.OFFLINE)
        self.transition(LifecycleState.STARTING)
        self.transition(LifecycleState.ACTIVE)
        return {"ok": True, "state": self._state}

    def pause(self) -> dict:
        """Idempotent pause: ACTIVE→PAUSED."""
        if self._state == LifecycleState.PAUSED:
            return {"ok": True, "state": self._state, "note": "already paused"}
        if self._state != LifecycleState.ACTIVE:
            return {"ok": False, "state": self._state, "note": "must be ACTIVE to pause"}
        self.transition(LifecycleState.PAUSED)
        return {"ok": True, "state": self._state}

    def resume(self) -> dict:
        """Resume from PAUSED→ACTIVE."""
        if self._state == LifecycleState.ACTIVE:
            return {"ok": True, "state": self._state, "note": "already active"}
        if self._state != LifecycleState.PAUSED:
            return {"ok": False, "state": self._state, "note": "must be PAUSED to resume"}
        self.transition(LifecycleState.ACTIVE)
        return {"ok": True, "state": self._state}

    def shutdown(self) -> dict:
        """Idempotent shutdown: ACTIVE|PAUSED→STOPPING→OFFLINE."""
        if self._state == LifecycleState.OFFLINE:
            return {"ok": True, "state": self._state, "note": "already offline"}
        if self._state not in (LifecycleState.ACTIVE, LifecycleState.PAUSED, LifecycleState.STOPPING):
            return {"ok": False, "state": self._state, "note": f"cannot shutdown from {self._state}"}
        if self._state != LifecycleState.STOPPING:
            self.transition(LifecycleState.STOPPING)
        self.transition(LifecycleState.OFFLINE)
        self._started_at = None
        return {"ok": True, "state": self._state}


# Module-level singleton — the single authority
lifecycle = Lifecycle()
