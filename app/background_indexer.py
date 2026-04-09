"""
Background indexer — Phase 4: Proactive Indexing.

Single daemon thread that runs scan_all when BOTH conditions are true:
  - is_idle()    : system idle >= 5 minutes
  - _battery_ok(): on AC power OR battery level >= 10%

Night window (2am–7am) is informational only — indexing runs whenever
idle+battery_ok regardless of time.

Thread runs at nice +19 (lowest priority, best-effort on macOS).
Checks every 5 seconds for near-instant pause when user resumes activity.
Inter-file duty cycle sleep: 0.15s on AC, 0.5s on battery to protect battery.

Invariant: only start() and stop() are called from outside this module.
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone

import psutil

from app.idle_detector import is_idle
from app.charging_gate import is_charging
from app.night_window import in_night_window
from app.ingest import scan_docs
import app.connectors.files as file_connector
import app.connectors.gmail as gmail_connector
import app.connectors.calendar as calendar_connector
import app.connectors.contacts as contacts_connector
import app.connectors.notes as notes_connector
import app.connectors.weather as weather_connector
import app.connectors.hue as hue_connector
import app.connectors.news as news_connector

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 5
INTER_FILE_SLEEP_SECONDS = 0.15        # duty cycle on AC power
INTER_FILE_SLEEP_ON_BATTERY = 0.5      # duty cycle on battery (gentler)


def _battery_ok() -> bool:
    """True if on AC power, battery ≥ 10%, or no battery (desktop Mac)."""
    try:
        batt = psutil.sensors_battery()
        if batt is None:
            return True   # desktop Mac — always OK
        if batt.power_plugged:
            return True
        return batt.percent >= 10.0
    except Exception:
        return True   # fail-safe: allow indexing


class BackgroundIndexer:
    """
    Manages the single background indexing thread.
    Thread is a daemon so it never blocks process shutdown.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._scan_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status: dict = {
            "running": False,
            "last_scan_at": None,
            "last_scan_result": None,
            "scan_count": 0,
            "current_scan": None,   # name of connector currently scanning, or None
            "conditions": {
                "idle": False,
                "battery_ok": False,   # True if on AC or battery >= 10%
                "in_night_window": False,  # informational only — not a gate
            },
        }

    def start(self) -> None:
        """Start the background thread. No-op if already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="background-indexer",
            daemon=True,
        )
        self._thread.start()
        with self._status_lock:
            self._status["running"] = True
        logger.info("Background indexer started")

    def stop(self) -> None:
        """Signal the thread to stop. Waits up to 5 seconds."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        with self._status_lock:
            self._status["running"] = False
        logger.info("Background indexer stopped")

    def get_status(self) -> dict:
        """Return a snapshot of the indexer's current state. Thread-safe."""
        with self._status_lock:
            return dict(self._status)

    # ── Private ───────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Main thread loop. Runs at nice +19 (low priority, best-effort)."""
        try:
            os.nice(19)
        except OSError:
            pass  # May fail if already at minimum priority; non-fatal

        while not self._stop_event.is_set():
            self._check_and_scan()
            # Sleep in 1-second increments to respond promptly to stop()
            for _ in range(CHECK_INTERVAL_SECONDS):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

    def _check_and_scan(self) -> None:
        """Evaluate gate conditions and trigger a scan if both pass (idle + battery_ok)."""
        idle = is_idle()
        battery_ok = _battery_ok()

        with self._status_lock:
            self._status["conditions"] = {
                "idle": idle,
                "battery_ok": battery_ok,
                "charging": is_charging(),  # kept for dashboard display
                "in_night_window": in_night_window(),  # informational only
            }

        if not (idle and battery_ok):
            return

        # Non-blocking acquire: skip cycle if a scan is already in progress
        if not self._scan_lock.acquire(blocking=False):
            logger.debug("Background indexer: scan already in progress, skipping")
            return

        try:
            self._run_scan()
        finally:
            self._scan_lock.release()

    def _run_scan(self) -> None:
        """Execute a full scan of all connectors. Records result in status."""
        started_at = datetime.now(timezone.utc).isoformat()
        logger.info("Background indexer: proactive scan started at %s", started_at)
        results: dict = {}

        with self._status_lock:
            self._status["current_scan"] = "docs"
        try:
            results["docs"] = scan_docs()
        except Exception as exc:
            results["docs"] = {"status": "ERROR", "message": str(exc)}

        sleep_secs = INTER_FILE_SLEEP_SECONDS if is_charging() else INTER_FILE_SLEEP_ON_BATTERY

        for name, connector in [
            ("files", file_connector),
            ("gmail", gmail_connector),
            ("calendar", calendar_connector),
            ("contacts", contacts_connector),
            ("notes", notes_connector),
            ("weather", weather_connector),
            ("hue", hue_connector),
            ("news", news_connector),
        ]:
            if self._stop_event.is_set():
                logger.info("Background indexer: stop requested mid-scan, aborting")
                break
            with self._status_lock:
                self._status["current_scan"] = name
            try:
                results[name] = connector.scan()
            except Exception as exc:
                results[name] = {"status": "ERROR", "message": str(exc)}
            time.sleep(sleep_secs)

        with self._status_lock:
            self._status["current_scan"] = None
            self._status["last_scan_at"] = started_at
            self._status["last_scan_result"] = results
            self._status["scan_count"] += 1

        logger.info("Background indexer: scan complete (total scans: %d)", self._status["scan_count"])

        # Refresh suggestion cache during night window idle — non-blocking
        if in_night_window():
            try:
                from app.suggestion_engine import maybe_refresh
                maybe_refresh()
            except Exception as exc:
                logger.debug("Suggestion engine refresh failed: %s", exc)


# Module-level singleton — imported by main.py
indexer = BackgroundIndexer()
