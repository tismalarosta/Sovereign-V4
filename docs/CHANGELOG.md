# CHANGELOG.md

All changes to Sovereign V3 are logged here. Newest entries at the top. Append-only — never edit past entries.

---

## [Phase 11 INFO-01] NewsAPI Connector — 2026-04-09

- **INFO-01** `app/connectors/news.py` NEW — NewsAPI.org top headlines connector: `fetch_headlines()` GET `newsapi.org/v2/top-headlines` (language=en, pageSize=20); 2-hour in-memory cache; `_BLOCKED_DOMAINS` frozenset (9 domains: dailymail.co.uk, thesun.co.uk, nypost.com, rt.com, sputniknews.com, breitbart.com, infowars.com, naturalnews.com, zerohedge.com) filters articles before indexing; `scan()` deletes stale `source_type=news` entries then upserts chunks with `news::date::hash` IDs; graceful NOT_CONFIGURED if key absent
- **INFO-01** `app/main.py` — `GET /news` endpoint (2-hour cache); `"news": news_connector` in `_CONNECTORS`; `_source_type` handles `news::` prefix; `open_news_article` keywords added; `_extract_action_params` extracts URL from message
- **INFO-01** `app/policy_engine.py` — `open_news_article: LOW`
- **INFO-01** `app/execution_engine.py` — `_execute_open_news_article` delegates to `_execute_open_url`; wired in `_ACTION_HANDLERS`
- **INFO-01** `app/confidence.py` — `open_news_article`: required=["url"], base=0.90
- **INFO-01** `app/background_indexer.py` — `news_connector` added to scan loop
- **TESTS** `tests/test_phase11.py` NEW — 15 tests: policy LOW, confidence entries, NOT_CONFIGURED (fetch + scan), blocked domain filtering (3 blocked + 2 allowed + integration), cache TTL hit, source_type, _CONNECTORS key, /news endpoint defined, handler wired, graceful no-URL
- **REGRESSION** 187/187 tests pass (172 prior + 15 new)

---

## [Phase 13 partial] Gemma 4 E4B LLM Upgrade — 2026-04-09

- **LLM-01** `app/ollama_client.py` — `MODEL` constant now reads from `settings.llm_model` (imported from `app.settings`); default switched from `"mistral"` to `"gemma4:e4b"`; docstring updated from "Mistral" to "Gemma 4 E4B"; no changes to `generate()` or `generate_stream()` interface — same Ollama `/api/generate` endpoint works for both models
- **LLM-01** `app/settings.py` — `llm_model: str = "gemma4:e4b"` field added; override via `LLM_MODEL=` in `data/.env` without code change
- **LLM-03** `app/main.py` — chat endpoint: `n_results=5` → `n_results=12`; Gemma 4's 128K context handles 12 chunks without truncation (was limited to 5 for Mistral's 8K window)
- **LLM-03** `app/suggestion_engine.py` — file and email context snippets: 2 → 3 per source; docstring updated from "Mistral" to "LLM"
- **TESTS** `tests/test_phase13.py` NEW — 7 tests: MODEL default is gemma4:e4b, settings field present, settings default via /dev/null env, generate() sends configured model in payload, generate_stream() sends configured model, chat uses n_results=12, suggestion engine uses 3 snippets per source
- **REGRESSION** 172/172 tests pass (165 prior + 7 new Phase 13)
- **PENDING** Pull model: update Ollama to ≥0.20.x then `ollama pull gemma4:e4b`; LLM-02 (function calling) deferred until model is live for testing

---

## [Session 2026-04-09] Documentation Sync + Setup Guide + Roadmap Update

- **DOCS** `docs/SETUP_GUIDE.md` NEW — complete step-by-step setup instructions for all services: Gmail/Calendar OAuth (Google Cloud project → credentials → first scan flow → token auto-refresh), OpenWeather API (free tier One Call 3.0), Philips Hue Bridge (find IP in Hue app, press button + POST to get token), Telegram Bot (BotFather flow + user ID via @userinfobot), NewsAPI, macOS permissions (Contacts, Notes Automation, Microphone), server restart commands, API token retrieval, verification curl commands; future services table (Phases 13–15)
- **DOCS** `docs/PHASE_STATUS.md` — Phase 10 tasks and unlock criteria marked `[x]` (were incorrectly left unchecked); Phase 11 prerequisite `[x]`; Phase 12 security prerequisite updated to reflect existing hardening; Phase 12 daily digest updated to mention optional TTS spoken briefing; **Phases 13–15 added**:
  - Phase 13: LLM upgrade to Gemma 4 E4B + native function calling + optional MLX backend
  - Phase 14: Trace learning loop (SQLite traces table) + orchestrator multi-step agent + context-aware routing (inspired by OpenJARVIS Stanford research)
  - Phase 15: Apple Health connector + Spotify connector + MCP client (Home Assistant, Obsidian) + RSS/HN feeds
- **DOCS** `docs/CURRENT_STATE.md` — removed 4 stale/contradictory lines (server-side weather, email stub claim, launchd "not loaded" note); fixed Ollama model name typo ("mistrat" → "mistral"); added Phases 7–10 to bottom phase summary
- **DOCS** `AGENTS.md` — LLM row updated to mention Gemma 4 E4B upgrade in Phase 13; endpoint cap updated (Phase 10 actual ~38, new cap 45 through Phase 12); SETUP_GUIDE.md added to canonical docs list

---

## [Phase 10] OpenWeather Upgrade + Philips Hue — 2026-04-08

- **HOME-01** `app/connectors/weather.py` NEW — OpenWeather One Call 3.0 API; 30-min in-memory cache (`_cache` dict + `fetched_at` timestamp); IP geolocation via ipapi.co (same as former client-side call, now server-side); graceful NOT_CONFIGURED if `OPENWEATHER_KEY` empty in `data/.env`; daily forecasts upserted to ChromaDB (`weather::YYYY-MM-DD` chunk IDs, source_type "weather"); HTTP errors caught and returned as `{"status": "ERROR"}`
- **HOME-01** `app/main.py` — `GET /weather` endpoint (auth + rate-limit); weather + hue connectors imported and added to `_CONNECTORS` dict and background indexer scan loop
- **HOME-01** `app/dashboard.html` — replaced `loadWeather(lat,lon,city)` + `loadWeatherByIP()` Open-Meteo fetch with `loadWeather()` calling `api('GET', '/weather')`; hover card upgraded to show current conditions + 3-day forecast with precipitation %; OpenWeather icon code → emoji map (`_WX_ICONS`); auto-refreshes every 30 min via `setInterval`
- **HOME-02** `app/connectors/hue.py` NEW — Philips Hue Bridge v1 LAN REST API; `turn_on(light_id)` / `turn_off(light_id)` return `undo_data`; `set_brightness(light_id, bri)` clamps 0–254; `set_color(light_id, hue, sat)` clamps hue 0–65535 and sat 0–254; `set_scene(scene_id, group_id)` validates non-empty scene_id; `get_lights()` / `get_scenes()` read-only; `scan()` indexes light names + scene names into ChromaDB; all functions return consistent `{success, message, undo_data}` or `{status, message}` shape; graceful NOT_CONFIGURED on empty bridge IP/token
- **HOME-02** `app/policy_engine.py` — 5 new LOW risk entries: `hue_turn_on`, `hue_turn_off`, `hue_set_brightness`, `hue_set_color`, `hue_set_scene`
- **HOME-02** `app/execution_engine.py` — 5 new handlers `_execute_hue_*` delegating to hue connector; added to `_ACTION_HANDLERS`
- **HOME-02** `app/confidence.py` — 5 new entries in `_REQUIRED_PARAMS` (e.g. set_brightness needs light_id+brightness) and `_BASE_CONFIDENCE` (turn_on/off 0.88, set_scene 0.85, set_brightness 0.85, set_color 0.82)
- **HOME-02** `app/main.py` — Hue chat keywords in `_ACTION_KEYWORDS`: "turn on/off the lights", "lights on/off", "dim the lights", "dim to", "movie mode", "reading mode", "set scene", "activate scene"; brightness % extraction in `_extract_action_params`; `GET /hue/lights` + `GET /hue/scenes` read endpoints
- **Dashboard** — "Pause API" button renamed to "Pause Server" (HTML + JS toggle label); behavior unchanged (returns 503 on all non-exempt endpoints, background indexer unaffected)
- Boot: OK, 165/165 tests pass (28 new + 41 + 47 + 34 + 15)

---

## [Session 2026-04-08] True State Audit + Server Fix + Docs Sync

### Root Cause Investigation
- Diagnosed why dashboard showed "Chunks=0, Last scan=Never run yet" — root cause: launchd-managed `uvicorn` process had been running since Thu 2026-04-02 and predated the `html.replace("__REGIS_TOKEN__", API_TOKEN)` line added to `app/main.py`. Every dashboard `api()` call was sending `Authorization: Bearer __REGIS_TOKEN__` literally → 401 on every authenticated endpoint → `api()` returns `{}` on `!r.ok` → all stats appear empty/zero.
- `pkill -f run.py` from previous sessions had ZERO effect because launchd runs `uvicorn app.main:app` directly, not `run.py`.
- Fixed by: `launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist` + `launchctl load` cycle.

### Verified Actual System State
- ChromaDB: **9,624 items** (8,194 files + 1,236 gmail + 194 other) — indexing was working all along
- SQLite: `scan_history` = 36 rows, `connectors` = 3 rows, no `chunks` table (data lives in ChromaDB)
- Gmail token at `data/.secrets/gmail_token.json`: **valid** — `_get_credentials()` returns live Credentials object
- Calendar: 0 items in ChromaDB, never successfully scanned
- `/system/stats` was missing `require_auth` in the old running process (security hole) — fixed by restart; new process enforces auth on all endpoints correctly

### Server Restart Protocol Established
- Correct restart command: `launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist && launchctl load ~/Library/LaunchAgents/com.regis.sovereign.plist`
- Verify: `launchctl list | grep regis`
- Old method (pkill) was silently failing for 5+ days

### Docs Updated
- `docs/CURRENT_STATE.md` — accurate ChromaDB count, Gmail/Calendar status, broken items, last boot
- `docs/PHASE_STATUS.md` — Phase 9 confirmed complete, Phase 10/11/12 plans added
- `docs/CHANGELOG.md` — this entry
- `docs/AGENT_MISTAKES.md` — three new entries: launchd kill method, dashboard zero state misread, connectors table misread

### New Feature Queued (Phase 10 backlog)
- Server on/off button for dashboard — stops/starts the Uvicorn API server only; never affects background indexer, suggestion engine, or launchd management

---
## [Phase 9 — Dashboard Fix] Contacts/Notes scan buttons + chip handlers — 2026-04-04

- **DASH-D** `app/dashboard.html` — Added "Scan Contacts" (👤) and "Scan Notes" (📝) buttons to the Index section; both call `scanConn()` like all other connectors; result parsed by existing `_scanSummary()` using `items_indexed` field
- **DASH-D** `app/dashboard.html` — `openChip()` extended with `'contacts'` case (fills chat with "What do you know about {name}?") and `'notes'` case (fills chat with "What's in my note: {title}?"); source key format `contacts::Name` / `notes::Title` — consistent with connector upsert patterns

---

## [Phase 9] macOS Deep Integration — 2026-04-03

- **DASH-A** `app/main.py` — `/system/ollama/stop` now starts with `osascript -e 'quit app "Ollama"'` (gracefully exits macOS menu-bar app before pkill, preventing auto-restart); SIGTERM tracked PID + pkill chain + 4s poll + SIGKILL fallback; `app/dashboard.html` `stopOllama()` 6-poll loop + `addSystemMsg('⚠ LLM could not be stopped…')` if Ollama still running after all attempts — frozen button bug eliminated
- **DASH-B** `app/background_indexer.py` — `current_scan` field added to status dict (set to connector name while scanning, None when idle, protected by `_status_lock`); contacts + notes added to scan loop; `app/dashboard.html` `pollSnapshot()` now reads `idx.current_scan` → updates index dot label to "Scanning X…" + applies indeterminate animation class to scan bar
- **DASH-C** `app/dashboard.html` — `pollSnapshot()` stats always populated: `s-last` gets `fmtTime()` or "Never run yet" (no more "—" on first boot); `s-count` uses `?? 0` fallback; if `current_scan` active, s-last overridden with "Scanning X… (in progress)"
- **MAC-01** `app/connectors/contacts.py` NEW — osascript exports all Apple Contacts as tab-separated (name, email, phone, company); `delete_by_filter({source_type: contacts})` before re-index; each contact embedded + upserted to ChromaDB (source_key `contacts::name`); 30s timeout, graceful NOT_CONFIGURED on permission denied; registered in `app/main.py` `_CONNECTORS` dict and `app/background_indexer.py` scan loop
- **MAC-02** `app/connectors/notes.py` NEW — AppleScript exports all Apple Notes using `===TITLE===`/`===BODY===`/`===END===` markers; `_BLOCKED_TITLE_KEYWORDS` frozenset (17 sensitive terms: passwords, credentials, ssh, secret, token, seed phrase, bank account, SSN, private key, etc.); `_is_blocked()` case-insensitive substring match; blocked notes silently skipped, never logged; text chunked 400 chars / 80 overlap; source_type "notes"; registered in `_CONNECTORS` and indexer
- **MAC-03** `app/automator.py` NEW — allowlisted osascript actions only, no arbitrary script execution: `set_volume(level)` clamps 0–10; `get_frontmost_app()` read-only System Events query; `show_notification(message, title)` sanitizes backslash+quote before embedding (200 char msg cap, 50 char title cap); `run_shortcut(name)` validates `^[A-Za-z0-9][A-Za-z0-9 \-]{0,63}$` — rejects if no match
- **MAC-01–03** `app/policy_engine.py` — 7 new entries: `open_contacts_card` LOW, `set_volume` LOW, `get_frontmost_app` LOW, `show_notification` LOW, `run_shortcut` MEDIUM, `create_note` MEDIUM, `append_to_note` MEDIUM
- **MAC-01–03** `app/confidence.py` — 7 new entries in `_REQUIRED_PARAMS` (e.g. set_volume needs "level", show_notification needs "message") and `_BASE_CONFIDENCE` (set_volume 0.90, show_notification 0.85, run_shortcut 0.78, create_note 0.75, etc.)
- **MAC-01–03** `app/execution_engine.py` — handlers added to `_ACTION_HANDLERS`: set_volume/get_frontmost_app/show_notification/run_shortcut delegate to `app.automator`; open_contacts_card opens Contacts.app via osascript
- `tests/test_phase9.py` NEW — 41 tests: policy tier classification for all 7 new actions; notes surface guard (16 title cases — blocked/not-blocked, case-insensitive, partial-match); run_shortcut name validation (empty, semicolons, backticks, dollar signs, leading space, too-long); show_notification escaping + truncation (mock); set_volume clamping (mock); confidence entries for all new actions
- Boot: OK, 137/137 tests pass (41 new + 47 confidence + 34 policy + 15 security)

---

## [Phase 8] Suggestions Decoupling + Gmail Live + LLM Fix — 2026-04-03

- **LLM-FIX** `app/main.py` — `/system/ollama/stop` now sends SIGTERM + pkill, polls Ollama's HTTP port for up to 4s to confirm process gone, escalates to SIGKILL if still alive; `/system/ollama/start` checks if already running before spawning (no double-start)
- **LLM-FIX** `app/dashboard.html` — `stopOllama()` wrapped in try/catch + 6×1s polling loop that re-enables button once dot turns red; `startOllama()` try/catch + 8×1.5s polling until green or timeout — frozen button bug eliminated
- **SUGG-01** `app/suggestion_engine.py` NEW — `get_cached()` reads `suggestions_cache` table (TTL 8h); `_generate_and_cache()` queries ChromaDB for calendar/email/file context, builds Mistral prompt, parses JSON array response, clears and repopulates cache; `maybe_refresh()` skips if cache fresh; `force_refresh()` unconditional
- **SUGG-01** `app/ingest.py` — `init_db()` creates `suggestions_cache` table (id, type, title, subtitle, text, source, generated_at)
- **SUGG-01** `app/background_indexer.py` — calls `suggestion_engine.maybe_refresh()` after each scan cycle when `in_night_window()`
- **SUGG-01** `app/main.py` `/suggestions` — reads LLM cache first; falls back to inline ChromaDB calendar/email/file queries if cache cold; returns up to 6 results (was 5)
- **GMAIL-01** `app/execution_engine.py` — `_execute_archive_email` wired: removes INBOX label via Gmail API, graceful stub if OAuth missing; `_execute_mark_read` wired: removes UNREAD label; `_execute_create_calendar_event` wired: `events().insert()` with title/start_time/end_time, returns event_id in undo_data; all three fall back to `success: False` + clear message if OAuth not configured
- Boot: OK, 96/96 tests pass

---

## [Phase 7] Confidence + Intelligence Upgrade — 2026-04-03

- **CONF-01** `app/confidence.py` — complete rewrite:
  - `_param_quality(param, value)` → per-param quality in [0.0,1.0]: `app_name` regex-validated (0.9/0.3), `path` existence check (1.0/0.4), `url` scheme check (0.9/0.3), `query` word-count (0.9/0.6), `email_id`/`event_id` hex pattern (0.9/0.4), unknown params 0.8, missing 0.0
  - Deduction formula changed from flat `-0.15 per missing` to `sum((1 - quality) * 0.30 per required param)` — bad `app_name` now deducts 0.21, missing param 0.30
  - `_get_feedback_boost()` — replaced flat 30-day window with exponential decay `exp(-days/7.0)`, half-life ~5 days; rejection window tightened to 3 days (was 7); penalty −0.12 (was −0.10); boost thresholds updated: total_weight≥2 & rate≥0.90 → +0.12, total_weight≥1 & rate≥0.75 → +0.07
  - `_time_modifier(action_type)` — NEW: penalizes `delete_file_trash`, `move_email`, `remove_email_label` by −0.08 when local hour ≥23 or <7
  - `_activity_boost()` — NEW: queries `chat_messages` table; if last message < 10 min ago → +0.05
  - `compute_confidence()` — combines all 5 dimensions: base − deduction + context_boost + feedback_boost + time_mod + activity
  - `interpret()` — upgraded to 4 tiers: <0.30 low, <0.50 medium-low, <0.70 medium, ≥0.70 high
- **CONF-02** `app/main.py` — `_proposal_hint()` replaced first-match keyword loop with weighted scoring: `weight = min(word_count / 3.0, 1.0)` — longer phrases beat shorter ones; regex fallback fixed at 0.55; `detection_score` passed as context to `compute_confidence()` and returned in hint dict
- `tests/test_confidence.py` NEW — 47 tests: param quality per type, compute_confidence cases, 4-tier interpret, time modifier, exponential decay feedback, scored intent detection
- Boot: OK, 96/96 tests pass

---

## [Phase 6.5 + Bug Fixes] UX Overhaul — 2026-04-03

- **PROPOSALS-FIX** `app/dashboard.html` — proposals panel complete overhaul: `_actionLabel()` maps `open_app` → "Open App" etc.; `_paramsSummary()` surfaces path/app_name/url/query inline in card; `_renderProposalCard()` unified renderer for pending+executed; `pollProposals()` now fetches both `status=PROPOSED` and `status=EXECUTED` in parallel — pending cards get Approve/Reject, executed cards get Undo button (`.p-btn.undo`); `doTransition()` confirmation now shows action label ("Approve: Open App?"); `doUndo()` calls `POST /transition/{id}` with `{new_status: "UNDO"}`; `.proposal-card.executed` CSS style; `.p-params` block shows key parameters; `.proposals-section-label` separates pending from recent
- **STREAM-FIX** `app/dashboard.html` — SSE stream now has 120s `AbortController` timeout to prevent indefinite hanging
- **MIC-FIX** `app/dashboard.html` — mic button error path now explicitly resets button state (`classList.remove('recording')`, text/disabled reset) before showing error message
- **CHIP-FIX** `app/dashboard.html` — `openChip()` now strips `file::` prefix before passing path to `open_finder`; docs chips now chat about the doc instead of attempting Finder open (docs are filename-only, inside blocked project root)
- **SUGG-FIX** `app/dashboard.html` — `openSuggSource()` strips `file::` prefix from suggestion source before passing to `open_finder`
- Boot: OK, 49/49 tests pass

---

## [Phase 6.5] Security Hardening — 2026-04-02

- **SEC-01** `app/auth.py` NEW — Bearer token auth; `_load_or_create_token()` generates/persists token at `data/.api_token` (chmod 600); `require_auth` FastAPI dependency raises 401 on missing/wrong token; `dashboard()` route injects token server-side via `html.replace("__REGIS_TOKEN__", API_TOKEN)`; dashboard.html `api()` and voice fetch now include `Authorization: Bearer` header
- **SEC-02** `app/rate_limiter.py` NEW — thread-safe sliding-window limiter; `chat_limiter` 10 req/min on `/chat` + `/propose`; `default_limiter` 60 req/min on all other protected endpoints; keyed by client IP
- **SEC-03** `app/execution_engine.py` — `_execute_open_app` now validates app name against `_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 \-\.]{0,63}$')`; `_execute_open_finder` now resolves path and guards against paths outside `Path.home()`
- **SEC-04** `app/main.py` — `ChatRequest.message: str = Field(..., max_length=4000)`; search queries capped at max_length=500; `ProposeRequest.action_type: str = Field(..., max_length=100)` + `@field_validator('parameters')` refusing > 15 keys
- **SEC-05** `app/audit.py` NEW — `AuditMiddleware(BaseHTTPMiddleware)` writes `{"ts","method","path","status","ip"}` JSONL lines to `data/audit.log` on every request; never logs bodies or auth headers
- **SEC-06** `data/.secrets/` created (chmod 700); `gmail_creds.json` + `gmail_token.json` moved there (chmod 600); `app/connectors/gmail.py` + `app/connectors/calendar.py` paths updated; `data/.env` created (chmod 600) with openweather/news/telegram/hue keys; `app/settings.py` NEW — `pydantic-settings BaseSettings` loading from `data/.env`; `.gitignore` created (secrets, DB, logs, pycache)
- **SEC-07** `app/main.py` — `_SecurityHeadersMiddleware`: sets `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'self'...`; `CORSMiddleware` allows localhost:8765 only
- `tests/test_security.py` NEW — 15 tests covering: 401 without/wrong token, rate limit 429, open_app bad names, open_finder system path, message/param size caps; all pass
- Boot: OK, 49/49 tests pass

---

## [Phase 6] Bug Fixes + Voice — Session 1 — 2026-04-02

- **BUG-01** `app/main.py` — fixed `pkill -f ollama` in lifespan teardown: now tracks `_ollama_pid` / `_ollama_started_by_us` globals; shutdown only sends SIGTERM to the specific PID that `/system/ollama/start` spawned; pre-existing Ollama instances are never killed
- **BUG-02** Voice input now live: `app/voice.py` (Whisper base model, lazy-loaded, temp-file transcription); `POST /voice/transcribe` endpoint registered in `app/main.py`; mic button added to dashboard with MediaRecorder API (hold to record → release → WebM blob → Whisper → fills chat input); recording animation (pulse-red); `requirements.txt` updated with `openai-whisper==20250625`, `sounddevice==0.5.5`, `soundfile==0.13.1`
- **BUG-03** `docs/CURRENT_STATE.md` — removed stale "Gmail NOT_CONFIGURED" note; replaced with accurate status: OAuth credentials present in `data/`, scan runs correctly
- **BUG-04** `docs/PHASE_STATUS.md` — Phase 4: marked `✅ COMPLETE — 2026-04-02`; Phase 5: marked `✅ COMPLETE — 2026-04-02`; voice criterion checked; energy impact criterion checked; Phase 6 added as current phase
- **BUG-05** `AGENTS.md` — Complexity Budget updated: Phase 5 baseline = 26 endpoints; Phase 6 cap = 32; Phase 7+ requires explicit budget update in AGENTS.md before adding endpoints
- **BUG-06** Stats top bar ERR fix — (A) `api()` in dashboard.html: `r.json()` now awaited inside try/catch + `!r.ok → return {}`; (B) `_statsFails` counter: ERR shown only after 3 consecutive failures; (C) `psutil.cpu_percent(interval=None)` in `/system/stats` (instant, uses cached measurement); warm-up call `psutil.cpu_percent()` added to lifespan startup
- Boot: OK, 34/34 tests pass

---

## [Phase 5.3] Functionality Fixes + Action Execution from Chat — 2026-04-02

- `app/main.py` — added `_extract_action_params(action_type, message)`: regex-based param extraction from natural language ("launch Photos" → `{app_name: "Photos"}`, "open my Downloads" → `{path: ~/Downloads}`, "search for X" → `{query: X}`); updated `_proposal_hint()` to include `params` in hint and use regex fallback patterns for natural speech like "launch X" / "open X"; `/chat` now auto-proposes+executes LOW-risk actions inline and returns `action_executed` in response (no separate `/propose` call needed); `_sse_stream()` carries `action_executed` in the first SSE meta frame; added `POST /system/ollama/start` endpoint (spawns `ollama serve`); added `import re, subprocess` at top; added folder-name keyword shortcuts ("my downloads", "my movies", etc.) to `_ACTION_KEYWORDS`
- `app/background_indexer.py` — replaced `charging` gate with `_battery_ok()`: runs indexing when idle + (AC power OR battery ≥ 10%); desktop Macs (no battery) always pass; added `INTER_FILE_SLEEP_ON_BATTERY = 0.5s` for gentler duty cycle on battery vs 0.15s on AC; status dict now reports `battery_ok` condition; `charging` kept in conditions dict for display
- `app/dashboard.html` — fixed **scan bar bug**: `id="scan-bar indeterminate"` (broken, space in ID) → `id="scan-bar"` with class applied dynamically; `checkOllama()` now shows/hides "Start LLM" button when LLM is offline; `startOllama()` calls `POST /system/ollama/start` and polls after 3s; `sendChat()` handles `action_executed` in SSE stream and shows `✓/✗ message` as system bubble in chat; `refreshStats()` shows `ERR` in top bar when server is unreachable (was silently `—`); weather replaced with IP-based geolocation via `ipapi.co` (browser geolocation was silently blocked in PyWebView); condition dot label updated: "On AC power" → "Battery ≥10% or AC power"; settings card text updated
- `~/Downloads/REGIS_RECAP.md` — NEW: plain-English status recap (what works, what doesn't, how to use OS actions, architecture, Ollama instructions)
- Boot: OK, 34/34 tests pass

---

## [Phase 5.2] Jarvis UI + OS Actions + Web Search + Confidence Learning — 2026-04-02

- `app/dashboard.html` — full glassmorphism redesign: frosted-glass cards (`backdrop-filter: blur(20px)`), green-glow borders, rounded corners, animated status dot, grid background; 3-column layout preserved; top bar with Regis logo, live state dot, weather, CPU/RAM/battery, clock; left panel is stacked glass cards (status, indexer controls, settings); center is glass chat card with persistent history loaded on start, timestamps per message, animated cursor while streaming, source chips, Web toggle button for DDG-augmented answers; right panel: proposals + smart prompts + stats+indexer conditions; scan progress bar (indeterminate animation while scanning)
- `app/main.py` — v0.5.0; auto-calls `lifecycle.start()` on boot (system always ACTIVE); `/chat` no longer returns 400 when nothing indexed (returns helpful guidance instead); `use_web: bool` field on ChatRequest supplements answers with DuckDuckGo search; saves user+assistant messages to `chat_messages` table; `GET /chat/history` (last 60 msgs); `DELETE /chat/history`; `GET /system/ollama` (check Ollama running + list models); `GET /search/web?q=...`; `GET /fetch/url?url=...`; `POST /connectors/force_index` (bypass idle/charging gates); updated `_ACTION_KEYWORDS` with open_finder/open_app/open_url/web_search; `log_feedback()` called on APPROVED/REJECTED transitions; `/connectors/all` scan now includes docs; endpoint count: 24
- `app/policy_engine.py` — added 4 new LOW-risk OS/UI actions: `open_finder`, `open_app`, `open_url`, `web_search`
- `app/execution_engine.py` — handlers: `open_finder` (subprocess `open -R` to reveal file or `open` dir), `open_app` (subprocess `open -a AppName`), `open_url` (Arc first, fallback default browser), `web_search` (DuckDuckGo search URL in Arc); URL-scheme safety check in open_url
- `app/web_search.py` — NEW: zero-trust web access; `_TextExtractor` HTML parser strips scripts/styles/forms; `fetch_url(url)` — validates scheme (https only), blocks localhost, 256KB read cap, sanitizes to 2000 chars plain text; `web_search(query)` — DuckDuckGo Instant Answer API, no key required, returns abstract + related topics; `format_for_llm()` — wraps all web content in `[UNTRUSTED WEB CONTENT]` markers to prevent prompt injection
- `app/confidence.py` — added adaptive learning: `log_feedback(action_type, approved)` writes to `feedback_log`; `_get_feedback_boost(action_type)` queries last 30 days — ≥3 approvals at ≥80% rate → +0.08, ≥5 at ≥90% → +0.12, any rejection in last 7 days → −0.10; boost applied in `compute_confidence()`; new actions added to `_REQUIRED_PARAMS` and `_BASE_CONFIDENCE`
- `app/ingest.py` — added `chat_messages(id,role,content,created_at)` and `feedback_log(id,action_type,approved,created_at)` tables to `init_db()`
- Boot: OK, 34/34 tests pass

---

## [Phase 5.1] Proactive Indexing Improvements + Dashboard Redesign — 2026-03-31

- `app/night_window.py` — changed window from 23:00–06:00 to 02:00–07:00
- `app/background_indexer.py` — gate is now idle+charging only (night_window removed as hard gate, retained as informational field); CHECK_INTERVAL_SECONDS 60→5 for near-instant pause; INTER_FILE_SLEEP_SECONDS=0.15 duty cycle between connector scans (~60% CPU ceiling combined with nice +19); stop_event checked mid-scan for immediate abort on user activity
- `app/connectors/files.py` — expanded ALLOWED_PATHS: ~/Downloads + iCloud Drive (~Library/Mobile Documents/com~apple~CloudDocs); added 9 user-specified blocked paths (Zoom, My Games, GitHub, Adobe, Claude, 4 iCloud app folders); expanded SUPPORTED_EXTENSIONS to include .docx, .jpg, .jpeg, .png, .mp4, .mov, .mp3, .m4a, .wav, .flac; TEXT_MAX_BYTES=50MB / MEDIA_MAX_BYTES=500MB size guards; `_extract_docx()` via python-docx; `_extract_image()` via Pillow (EXIF: camera, GPS, date, dimensions) + optional BLIP captioning (CAPTION_IMAGES=False default); `_extract_media()` via mutagen (title, artist, album, genre, duration, bitrate); dispatch by extension in scan() loop; images+media produce single chunks (no overlap needed)
- `app/main.py` — added GET /system/stats (psutil: cpu_percent, ram_percent, battery_percent, battery_charging); added GET /suggestions (ChromaDB searches for upcoming meetings and unread emails, returns top 5 clickable prompts); version stays 0.4.0; endpoint count: 18
- `app/dashboard.html` — full rewrite: 3-column layout (left 220px controls+settings, center flex chat, right 280px proposals+suggestions+stats); top bar: weather via Open-Meteo free API with geolocation + hover tooltip, CPU/RAM/battery via /system/stats polled every 5s, clock updated every second; left panel: state badge, lifecycle buttons, scan buttons, collapsible settings; center: streaming SSE chat with source chips (Enter to send); right: proposals with approve/reject, smart prompts (clickable → fills chat), stats + indexer condition dots; night-window dot is amber (informational), idle+charging dots are green (gate)
- `requirements.txt` — added psutil==7.2.2, Pillow==12.2.0, mutagen==1.47.0, python-docx==1.2.0
- Boot: OK, 34/34 tests pass

---

## [Phase 5] Interface & Expansion — 2026-03-31

- `app/ollama_client.py` — added `generate_stream()`: httpx streaming generator, yields one token at a time; `stream: True` payload to Ollama
- `app/main.py` — `/chat` now accepts `?stream=true` query param; returns `StreamingResponse` with SSE (`data: {token}` / `data: [DONE]`); non-streaming path preserved; `response_model=None` to allow dual return type; version 0.5.0
- `app/window.py` — PyWebView native macOS window (1200×800, resizable, WebKit); `open_window()` blocks on main thread as macOS requires
- `run.py` — launcher: checks if port 8765 already listening; starts uvicorn in daemon thread if not; waits up to 30s for server; opens PyWebView window on main thread
- `app/dashboard.html` — full redesign: sidebar navigation (Chat/Search/Proposals/Connectors/Indexer); dark theme (#0a0a0a / #e0e0e0 / accent #00ff88); streaming chat with SSE token rendering + cursor blink; collapsible source chips; source-type filter in Search; Proposals with confirmation dialogs; Connectors scan buttons with inline log; Indexer condition indicators; auto-resize textarea; Enter-to-send shortcut
- `requirements.txt` — added pywebview==6.1
- Voice input: skipped — ffmpeg not installed on this machine (stretch goal, deferred to future session)
- Boot: OK (< 20s, all existing tests pass 34/34)

---

## [Phase 4] Proactive Indexing — 2026-03-31

- `app/idle_detector.py` — macOS idle time via `ioreg IOHIDSystem HIDIdleTime` (nanoseconds); threshold 5 min; `is_idle() -> bool`, `get_idle_seconds() -> float`
- `app/charging_gate.py` — AC power detection via `pmset -g batt`; `is_charging() -> bool`; fail-safe returns False on error
- `app/night_window.py` — `in_night_window() -> bool`; True between 23:00 and 06:00 local time
- `app/background_indexer.py` — daemon thread at nice +19; checks every 60s; triggers scan_all when idle AND charging AND night window; non-blocking scan lock; `start()`, `stop()`, `get_status()` API
- `app/main.py` — converted to lifespan event (asynccontextmanager); starts/stops indexer on app boot/shutdown; `GET /indexer/status` endpoint; `/snapshot` now includes `indexer` key; version 0.4.0
- `app/dashboard.html` — Background Indexer panel with live idle/charging/night-window indicators (green/grey), last scan time, auto-scan count
- `~/Library/LaunchAgents/com.regis.sovereign.plist` — auto-starts uvicorn on login; KeepAlive restart-on-crash; ThrottleInterval 10s; logs to `data/regis.stdout.log` / `data/regis.stderr.log`; `plutil -lint` passes
- `pyrightconfig.json` — added to resolve venv imports in Pyright
- Endpoint count: 16 (Phase 3 added 3, Phase 4 adds 1)
- Boot: OK (< 20s, background thread starts without blocking)

---

## [Phase 3] Policy & Execution — 2026-03-31

- `app/policy_engine.py` — ONLY policy authority; explicit allow-list; unknown actions = ULTRA (deny-by-default); LOW/MEDIUM allowed, HIGH/ULTRA hard-denied
- `app/confidence.py` — deterministic confidence scorer (0.0–1.0); base scores per action + deductions for missing params + context boost; three-tier interpretation
- `app/proposal_manager.py` — proposal lifecycle in SQLite: PROPOSED → APPROVED → EXECUTING → EXECUTED/FAILED/REJECTED; ULTRA/HIGH immediately rejected; undo_data stored for MEDIUM
- `app/execution_engine.py` — ONLY mutation authority; journal written BEFORE execution; belt-and-suspenders policy re-check; handlers for archive_email, mark_read, rebuild_index, create_calendar_event, delete_file_trash, move_email; undo for delete_file_trash (real), stubs for OAuth actions
- `app/ingest.py` — init_db() now creates proposals + action_journal tables
- `app/main.py` — added POST /propose (LOW auto-executes, MEDIUM requires approval, ULTRA/HIGH rejected); GET /proposals; POST /transition/{id} (approve/reject/undo); /chat now emits proposal_hint on action intent keywords; version stays 0.3.0; endpoint count: 15
- `app/dashboard.html` — Proposals panel with risk-tier color badges, Approve/Reject/Undo buttons, auto-refresh every 3s
- `tests/__init__.py` — tests package
- `tests/test_policy_engine.py` — 34 test cases covering LOW/MEDIUM/HIGH/ULTRA/unknown/bypass/SQL-injection/return-type
- `docs/PHASE_STATUS.md` — Phase 3 IN PROGRESS, all criteria checked
- All actions journaled before execution (not after)
- No execution without explicit approval for MEDIUM+
- ULTRA = immediately REJECTED, no override, ever

---

## [Phase 2] Data Connectors — 2026-03-31

- `app/connectors/__init__.py` — connectors package
- `app/connectors/files.py` — local file connector: scans ~/Documents, ~/Desktop; types .txt .md .pdf .py; surface guard blocks system/project paths; 175 files / 2758 chunks indexed
- `app/connectors/gmail.py` — Gmail connector: OAuth2 read-only, last 30 days inbox+sent; gracefully skips if creds not configured
- `app/connectors/calendar.py` — Calendar connector: OAuth2 read-only, past 7 + next 30 days; reuses Gmail OAuth token
- `app/ingest.py` — added connectors table to init_db() (name, last_run, items_indexed, status)
- `app/snapshot.py` — snapshot now includes connectors[] summary from SQLite
- `app/main.py` — added POST /connectors/{name}/scan (files|gmail|calendar|all); updated /chat with source_type citations; version 0.3.0
- `app/dashboard.html` — connector status panel showing per-connector last_run/items/status; Scan buttons per connector + Scan All
- `requirements.txt` — added google-api-python-client, google-auth-oauthlib, google-auth-httplib2, pypdf and deps
- `docs/task_updates/2026-03-31_gmail-setup.md` — OAuth setup guide for Gmail + Calendar
- Endpoint count: 12 (within Phase 1-2 budget)
- Boot time: < 8s (well within 20s limit)
- SQLite connectors table persists across restarts

---

## [Phase 1] Intelligence Core — 2026-03-31

- sentence-transformers (MiniLM-L6-v2) + ChromaDB installed, pinned to requirements.txt
- `app/embeddings.py` — singleton Embedder, local MiniLM-L6-v2
- `app/chroma_store.py` — singleton ChromaStore at data/chroma/, cosine similarity
- `app/ingest.py` — scans docs/*.md, chunks (400 chars / 80 overlap), embeds, upserts; idempotent
- `app/ollama_client.py` — HTTP client to local Ollama/Mistral
- `app/main.py` — added /scan_docs, /search, /chat, /scan_history endpoints
- `app/dashboard.html` — chat interface with Scan Docs button
- SQLite data/regis.db — scan_history table persists across restarts
- All Phase 1 unlock criteria met: 6 docs / 54 chunks indexed, 10/10 queries stable, boot 4.5s

---

## [Phase 0] Foundation Scaffolded — 2026-03-31

- Python 3.12 venv created at `venv/`
- Installed: fastapi, uvicorn, pydantic, rich — pinned to `requirements.txt`
- `app/lifecycle.py` — Lifecycle state machine (OFFLINE/STARTING/ACTIVE/PAUSED/STOPPING/ERROR), idempotent transitions
- `app/snapshot.py` — Single snapshot authority; returns JSON from lifecycle state only
- `app/main.py` — FastAPI app with `/health`, `/snapshot`, `/start`, `/pause`, `/resume`, `/shutdown`, `/dashboard`
- `app/dashboard.html` — Minimal dashboard polling `/snapshot` every 2 seconds
- Boot verified: `/health` 200, `/snapshot` valid JSON, lifecycle transitions all pass
- No background workers, no database, no LLM — Phase 0 only

---

## [Phase 0] Project Initialized — 2026-03-30

- Sovereign V3 folder created
- AGENTS.md, CLAUDE.md established as governance layer
- Core docs scaffolded: INVARIANTS.md, PHASE_STATUS.md, RISK_MODEL.md, AGENT_MISTAKES.md, CHANGELOG.md
- Inherited institutional knowledge from V1 and V2 logged in AGENT_MISTAKES.md
- Phase 0 declared: Foundation (not started)
