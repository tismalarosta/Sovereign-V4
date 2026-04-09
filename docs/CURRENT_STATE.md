# CURRENT_STATE.md

This file is updated after every completed task. It is the ground truth for what is currently working.

---

## Last Updated: 2026-04-09 (Phase 11 INFO-01 — NewsAPI connector)

## Phase: 11 IN PROGRESS 🔄 — INFO-01 done; Phase 13 LLM-01+LLM-03 also done (model downloading)

## What Works
- Python 3.12 venv at `venv/` — Python 3.12.13
- FastAPI + Uvicorn boots in ~8s (< 20s limit)
- `run.py` — launch via `./venv/bin/python run.py`; starts server + opens native macOS WebKit window
- `/health` — 200 always
- `/snapshot` — valid JSON, includes `chunks_indexed`, `connectors[]`, and `indexer` status
- `/start`, `/pause`, `/resume`, `/shutdown` — idempotent lifecycle
- `/scan_docs` — scans docs/*.md, chunks, embeds, stores in ChromaDB
- `/search` — semantic search across ALL sources (docs + files + gmail + calendar)
- `/chat` — retrieves context; non-streaming (default) or SSE streaming via `?stream=true`; emits proposal_hint on action intent
- `app/window.py` — PyWebView 1200×800 macOS native window
- `app/ollama_client.py` — `generate_stream()` generator for token-by-token SSE output
- `/scan_history` — SQLite-backed, persists across restarts
- `/connectors/{name}/scan` — name: files | gmail | calendar | contacts | notes | all
  - files: scans ~/Documents, ~/Desktop, ~/Downloads, iCloud Drive; rich types: .docx, .jpg, .jpeg, .png, .mp4, .mov, .mp3, .m4a, .wav, .flac; EXIF + mutagen metadata; 9 noisy paths blocked
  - gmail: graceful NOT_CONFIGURED skip (OAuth credentials not set up yet)
  - calendar: graceful NOT_CONFIGURED skip (reuses Gmail OAuth)
  - all: runs all connectors sequentially, never crashes
- `/propose` — policy engine classifies action; LOW auto-executes (conf ≥ 0.30); MEDIUM requires approval; ULTRA/HIGH immediately rejected
- `/proposals` — list all proposals (filterable by status)
- `/transition/{id}` — approve/reject/undo proposals; APPROVED triggers execution
- `/indexer/status` — background indexer state: running, conditions (idle/charging/night), last_scan_at, scan_count
- `/dashboard` — glassmorphism redesign: frosted-glass cards, green-glow borders, animated state dot, chat history, Web toggle, scan progress bar, Ollama status indicator
- `/system/stats` — psutil: cpu_percent, ram_percent, battery_percent, battery_charging
- `/system/ollama` — check Ollama running + list loaded models
- `/suggestions` — context-aware smart prompts from ChromaDB
- `/chat/history` — last 60 chat messages from SQLite; DELETE to clear
- `/search/web` — DuckDuckGo Instant Answer with zero-trust sanitization
- `/fetch/url` — sanitized URL fetch (plain text only, script-stripped)
- `/connectors/force_index` — bypass idle/charging gates, index everything now
- `app/policy_engine.py` — open_finder, open_app, open_url, web_search (all LOW risk)
- `app/execution_engine.py` — OS action handlers: Finder reveal, app launch, Arc URL open
- `app/web_search.py` — NEW: zero-trust web access with prompt-injection protection
- `app/confidence.py` — adaptive learning: approval/rejection history boosts/penalizes confidence
- Confidence evolution: approving same action 3+ times → +0.08 boost; rejection in last 7 days → −0.10 penalty
- `app/idle_detector.py` — ioreg IOHIDSystem HIDIdleTime, 5-min threshold, verified on M2
- `app/charging_gate.py` — pmset -g batt AC Power detection, fail-safe False on error
- `app/background_indexer.py` — gate now `idle + battery_ok` (≥10% OR AC OR no battery); 0.15s AC / 0.5s battery duty cycle
- Natural language action execution: say "launch Photos", "open Spotify", "show my Downloads", "search for X" in chat → executes automatically
- `/system/ollama/start` — starts `ollama serve` from UI; dashboard shows "Start LLM" button when LLM offline; tracks PID; teardown only kills Ollama it started
- Scan progress bar fixed (HTML ID bug was preventing animation)
- `~/Downloads/REGIS_RECAP.md` — human-readable status recap
- `app/voice.py` — Whisper base model transcription; `POST /voice/transcribe` endpoint; mic button in dashboard (hold to record)
- Stats top bar fixed: `api()` now awaits `r.json()` inside try/catch; 3-strike ERR threshold; `cpu_percent(interval=None)` + lifespan warm-up
- `app/night_window.py` — 02:00–07:00 local time window (informational — not a hard gate)
- `app/background_indexer.py` — daemon thread, nice +19, 5s check interval, idle+charging gate, 0.15s inter-file duty cycle, instant abort on stop_event, non-blocking scan lock
- `app/policy_engine.py` — single policy authority, deny-by-default for unknown actions
- `app/confidence.py` — deterministic scoring, param-based deductions, context boost
- `app/proposal_manager.py` — proposal lifecycle in SQLite, ULTRA/HIGH hard-rejected on creation
- `app/execution_engine.py` — journal before execution, belt-and-suspenders policy re-check, undo for MEDIUM
- `data/regis.db` — SQLite with scan_history + connectors + proposals + action_journal tables
- `data/chroma/` — ChromaDB with 9,624 total chunks (8,194 files + 1,236 gmail + 194 other)
- `data/.secrets/` — Gmail creds + token (chmod 700 dir, 600 files); token verified valid 2026-04-08
- `data/.env` — env vars for openweather/news/telegram/hue (chmod 600)
- `data/.api_token` — Bearer token for API auth (chmod 600, auto-generated on first boot)
- `app/auth.py` — Bearer token auth; `require_auth` dependency on all endpoints except `/health` + `/dashboard`
- `app/rate_limiter.py` — sliding-window limiter; 10 req/min chat, 60 req/min default
- `app/audit.py` — JSONL audit log at `data/audit.log` (method, path, status, IP, timestamp)
- `app/settings.py` — pydantic-settings loading from `data/.env`
- `.gitignore` — secrets, DB, logs, pycache excluded
- `requirements.txt` — fully pinned
- `tests/test_policy_engine.py` + `tests/test_security.py` + `tests/test_confidence.py` + `tests/test_phase9.py` + `tests/test_phase10.py` — 165 test cases, all passing
- `app/confidence.py` — Phase 7: `_param_quality()` per-param validation; exponential decay feedback; time-of-day modifier; session activity boost; 4-tier `interpret()`
- `app/main.py` `_proposal_hint()` — weighted intent scoring; `detection_score` returned in hint
- `/system/ollama/stop` — polls up to 4s to confirm process gone, SIGKILL fallback; Stop LLM button no longer freezes
- `/system/ollama/start` — double-start guard; Start LLM button polls until green
- `app/suggestion_engine.py` — LLM-powered suggestions cached in SQLite (8h TTL); generated during night-window idle by background indexer; `/suggestions` reads cache, falls back to inline ChromaDB if cold
- `app/execution_engine.py` — `archive_email`, `mark_read`, `create_calendar_event` wired with real Gmail/Calendar API; graceful stub if OAuth not configured
- Proposals panel: shows human-readable action labels, parameters inline, Approve/Reject for pending, Undo for executed; confirmation dialogs include action name
- Source chips: file chips strip `file::` prefix before Finder reveal; docs chips chat about the doc; calendar/gmail chips fill chat
- Suggestions: screenshot smart prompts (Desktop `Screenshot*.png`); `file::` prefix stripped before Finder open
- SSE stream: 120s AbortController timeout — no more indefinite hangs
- Mic button: error path properly resets button state on permission denial
- `~/Library/LaunchAgents/com.regis.sovereign.plist` — auto-start + restart-on-crash via launchd; plutil -lint passes; launchctl load confirmed working 2026-04-08

- `app/connectors/weather.py` — OpenWeather One Call 3.0; 30-min cache; source_type "weather"; `GET /weather` endpoint; graceful NOT_CONFIGURED if key absent
- `app/connectors/hue.py` — Philips Hue Bridge v1 LAN API; turn_on/off, set_brightness (0–254), set_color, set_scene; `GET /hue/lights` + `GET /hue/scenes`; scan indexes light + scene names; graceful NOT_CONFIGURED
- `app/connectors/news.py` — NewsAPI.org top headlines; language=en, pageSize=20; 2-hour in-memory cache; 9-domain tabloid blocklist (`dailymail`, `rt.com`, `breitbart`, etc.); `news::date::hash` chunk IDs; `GET /news` endpoint; `open_news_article` LOW-risk action; graceful NOT_CONFIGURED if key absent
- Dashboard weather: now server-side via `/weather` (not direct Open-Meteo); hover card shows 3-day forecast with precipitation
- Dashboard "Pause Server" button (was "Pause API") — pauses all API endpoints except health/dashboard, background indexer keeps running
- `app/connectors/contacts.py` — Apple Contacts indexer (osascript); source_type "contacts"; graceful NOT_CONFIGURED if permission denied
- `app/connectors/notes.py` — Apple Notes indexer (AppleScript); surface guard: 17-keyword blocklist on title (passwords, ssh, token, seed phrase, SSN, etc.); chunked 400/80; source_type "notes"; graceful NOT_CONFIGURED if permission denied
- Dashboard Index section: "Scan Contacts" (👤) and "Scan Notes" (📝) buttons added — now all 6 connectors have individual scan buttons
- `openChip()` in dashboard: handles 'contacts' source type (chat query about contact) and 'notes' source type (chat query about note title)
- `app/automator.py` — allowlisted macOS actions: set_volume, get_frontmost_app, show_notification (sanitized), run_shortcut (regex-validated name)
- `app/policy_engine.py` — Phase 9 actions: open_contacts_card LOW, set_volume LOW, get_frontmost_app LOW, show_notification LOW, run_shortcut MEDIUM, create_note MEDIUM, append_to_note MEDIUM
- Dashboard: Stop LLM button — no longer freezes; polls 6x and shows system message if Ollama persists
- Dashboard: Indexer stats — s-last shows "Never run yet" on first boot (was "—"); s-count shows 0 (was "—")
- Dashboard: Active scan label — shows "Scanning contacts…" etc. while background indexer is running

## What Is Broken / Known Issues
- **Gmail shows NOT_CONFIGURED on startup** — token is valid but startup scan records stale status. Run `POST /connectors/gmail/scan` after each server restart. 1,236 gmail items persist in ChromaDB from last successful run.
- **Calendar: never successfully indexed** — 0 items in ChromaDB. Connector code exists and reuses Gmail token. Run `POST /connectors/calendar/scan` to populate.
- **`pkill -f run.py` does NOT kill the launchd-managed server** — launchd runs `uvicorn` directly. Always restart via `launchctl unload/load ~/Library/LaunchAgents/com.regis.sovereign.plist`
- **Dashboard showed false Chunks=0 / Never run** — fixed 2026-04-08. Was caused by stale launchd process predating the token injection code; every `/snapshot` call returned 401.
- Contacts/Notes connectors require macOS permissions to be granted in System Preferences → Privacy (Contacts, Automation)
- delete_file_trash is fully real (moves to ~/.Trash with undo support)
- Energy impact over 24h not yet measured (Phase 4 final unlock criterion)
- OpenWeather + Hue require keys in `data/.env` before they activate — see `docs/SETUP_GUIDE.md`
- Contacts/Notes may need macOS permission grants on fresh systems — see `docs/SETUP_GUIDE.md`

## launchd Commands
```bash
# Load (start + autostart on login)
launchctl load ~/Library/LaunchAgents/com.regis.sovereign.plist

# Unload (stop + disable)
launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist

# Check status
launchctl list | grep regis

# View logs
tail -f ~/Sovereign\ V3/data/regis.stdout.log
```

## Environment Status
- Python 3.12: ✅ venv/bin/python = Python 3.12.13
- venv: ✅ created at venv/
- Ollama: ✅ mistral:latest (current); gemma4:e4b configured as default in code — pull after updating Ollama to ≥0.20.x
- FastAPI app: ✅ boots and serves
- Background indexer: ✅ starts on boot, conditions reporting correctly

## Last Successful Boot
- 2026-04-08: launchctl unload+load cycle; token injection confirmed; /system/stats enforces auth; /snapshot returns 9,624 chunks

## Phase 0 — COMPLETE ✅ (2026-03-31)
## Phase 1 — COMPLETE ✅ (2026-03-31)
## Phase 2 — COMPLETE ✅ (2026-03-31)
## Phase 3 — COMPLETE ✅ (2026-03-31)
All unlock criteria met: policy engine, confidence scoring, proposal lifecycle, undo, action journal.

## Phase 4 — COMPLETE ✅ (2026-03-31)
All unlock criteria met. Energy impact pending 24h measurement but functional.

## Phase 5 — COMPLETE ✅ (2026-04-02)
Native window, streaming chat, full dashboard redesign, voice input — all done.

## Phase 6 — COMPLETE ✅ (2026-04-02)
Bug fixes + voice: pkill fix, Whisper transcription, Gmail creds status, phase docs updated.

## Phase 6.5 — COMPLETE ✅ (2026-04-02)
All 7 security hardening steps done. 49/49 tests pass.

## Phase 7 — COMPLETE ✅ (2026-04-03)
Confidence overhaul: 5-dimension scoring, exponential decay feedback, time modifier, scored intent detection.

## Phase 8 — COMPLETE ✅ (2026-04-03)
Suggestion engine, Gmail/Calendar live execution, LLM stop/start fix, proposal panel overhaul.

## Phase 9 — COMPLETE ✅ (2026-04-03)
Contacts + Notes connectors, macOS Automator (set_volume, notifications, Shortcuts), dashboard bug fixes (stats, scan label, Stop LLM).

## Phase 10 — COMPLETE ✅ (2026-04-08)
OpenWeather server-side weather with 3-day forecast, Philips Hue LAN control, 5 Hue actions. 165/165 tests pass.

## Phase 11 — IN PROGRESS 🔄 (2026-04-09)
INFO-01 complete: NewsAPI connector, tabloid blocklist, /news endpoint, open_news_article action. 187/187 tests pass.

## Phase 13 — IN PROGRESS 🔄 (2026-04-09)
LLM-01: MODEL switched to gemma4:e4b via settings (LLM_MODEL= in data/.env). LLM-03: n_results 5→12 in chat, 2→3 snippets in suggestion engine. 187/187 tests pass. Pending: Ollama update + `ollama pull gemma4:e4b`, then LLM-02 (function calling).
