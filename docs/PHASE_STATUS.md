# PHASE_STATUS.md — Current Phase and Lock System

## Current Phase

**Phase 9 — macOS Deep Integration**
Status: ✅ COMPLETE — 2026-04-03

### Completed
- [x] Dashboard Bug A — `app/main.py` `/system/ollama/stop`: `osascript -e 'quit app "Ollama"'` first (handles auto-restart), then SIGTERM + pkill chain, 4s poll, SIGKILL fallback; `app/dashboard.html` `stopOllama()`: 6-poll loop + error message if still running after timeout
- [x] Dashboard Bug B — `app/background_indexer.py`: `current_scan` field in status (set per-connector while scanning, null when idle); `app/dashboard.html` `pollSnapshot()`: live "Scanning X…" label + indeterminate scan bar animation
- [x] Dashboard Bug C — `app/dashboard.html` `pollSnapshot()`: s-last always populated ("Never run yet" fallback), s-count always shows (0 fallback), no more "—" on first boot
- [x] MAC-01 — `app/connectors/contacts.py` NEW: osascript exports contacts (name, email, phone, company); ChromaDB upsert with source_type "contacts"; graceful NOT_CONFIGURED on permission denied; registered in `app/main.py` `_CONNECTORS` and background indexer scan loop
- [x] MAC-02 — `app/connectors/notes.py` NEW: AppleScript exports notes with title/body markers; `_BLOCKED_TITLE_KEYWORDS` frozenset (passwords, credentials, ssh, token, seed phrase, SSN, etc.); sensitive notes silently skipped, never logged; CHUNK_SIZE=400, overlap=80; source_type "notes"; registered in `_CONNECTORS` and background indexer
- [x] MAC-03 — `app/automator.py` NEW: allowlisted osascript actions only; `set_volume` (0–10 clamp), `get_frontmost_app` (read-only), `show_notification` (quote-escaped, 200-char cap), `run_shortcut` (regex-validated name `^[A-Za-z0-9][A-Za-z0-9 \-]{0,63}$`)
- [x] `app/policy_engine.py` — MAC-01–03 actions added: `open_contacts_card` LOW, `set_volume` LOW, `get_frontmost_app` LOW, `show_notification` LOW, `run_shortcut` MEDIUM, `create_note` MEDIUM, `append_to_note` MEDIUM
- [x] `app/confidence.py` — MAC-01–03 entries added to `_REQUIRED_PARAMS` and `_BASE_CONFIDENCE`
- [x] `app/execution_engine.py` — handlers for set_volume, get_frontmost_app, show_notification, run_shortcut, open_contacts_card all delegating to automator
- [x] `tests/test_phase9.py` NEW — 41 tests: policy tiers, notes surface guard (16 cases), automator input validation (run_shortcut name regex, show_notification escaping, set_volume clamping), confidence entries; all pass
- [x] Regression: 137 total tests pass (41 + 47 + 34 + 15)

**Phase 8 — Suggestions Decoupling + Gmail/Calendar Live**
Status: ✅ COMPLETE — 2026-04-03

### Completed
- [x] LLM-FIX — `app/main.py` `/system/ollama/stop`: sends SIGTERM + pkill, polls up to 4s to confirm process gone, SIGKILL fallback; `/system/ollama/start`: guards against double-start
- [x] LLM-FIX — `app/dashboard.html` `stopOllama()`: try/catch + polling loop (6×1s) until dot turns red; `startOllama()`: try/catch + polling loop (8×1.5s) until dot turns green — no more frozen buttons
- [x] SUGG-01 — `app/suggestion_engine.py` NEW: `get_cached()` reads SQLite `suggestions_cache` (TTL 8h); `_generate_and_cache()` queries ChromaDB, asks Mistral, parses JSON array, stores; `maybe_refresh()` called by background indexer during night window; `force_refresh()` for manual trigger
- [x] SUGG-01 — `app/ingest.py` `init_db()`: added `suggestions_cache` table
- [x] SUGG-01 — `app/background_indexer.py`: calls `suggestion_engine.maybe_refresh()` after each scan during night window
- [x] SUGG-01 — `app/main.py` `/suggestions`: reads LLM cache first, falls back to inline ChromaDB queries when cache cold; returns up to 6 results
- [x] GMAIL-01 — `app/execution_engine.py`: `_execute_archive_email`, `_execute_mark_read`, `_execute_create_calendar_event` all wired with real Gmail/Calendar API calls; graceful `success: False` if OAuth not configured; ImportError stub fallback if google-api not installed
- [x] Regression: 96/96 tests pass

**Phase 7 — Confidence + Intelligence Upgrade**
Status: ✅ COMPLETE — 2026-04-03

### Completed
- [x] CONF-01 — `app/confidence.py` rewritten: `_param_quality()` per-param quality scoring; `_get_feedback_boost()` exponential decay (half-life ~5 days, `exp(-days/7)`); `_time_modifier()` penalizes destructive actions 23:00–06:59; `_activity_boost()` +0.05 if user chatted in last 10 min; `compute_confidence()` combines all 5 dimensions; `interpret()` upgraded to 4 tiers
- [x] CONF-02 — `_proposal_hint()` in `app/main.py` replaced first-match loop with weighted scoring: `weight = min(word_count / 3.0, 1.0)`; regex fallback scores 0.55; `detection_score` passed into context; returned in hint dict
- [x] `tests/test_confidence.py` NEW — 47 tests covering all dimensions, 4-tier interpret, feedback decay, time modifier, scored intent detection; all pass
- [x] Regression: 49 existing tests still pass (96 total)

**Phase 6.5 — Security Hardening**
Status: ✅ COMPLETE — 2026-04-02

**Phase 6 — Bug Fixes + Voice**
Status: ✅ COMPLETE — 2026-04-02

**Phase 5 — Interface & Expansion**
Status: ✅ COMPLETE — 2026-04-02

**Phase 4 — Proactive Indexing**
Status: ✅ COMPLETE — 2026-04-02

**Phase 3 — Policy & Execution**
Status: ✅ COMPLETE — 2026-03-31

**Phase 2 — Data Connectors**
Status: ✅ COMPLETE — 2026-03-31

---

## Phase 0 — Foundation
Status: ✅ COMPLETE — 2026-03-31

---

## Phase 0 — Foundation

### Goal
Bootable skeleton with governance, zero features.

### Allowed
- Folder structure and all governance docs
- Virtual environment (Python 3.12)
- Bare FastAPI + Uvicorn app
- Ollama installed and health-checked (not yet integrated into app)
- `/health` endpoint (always 200)
- `/snapshot` endpoint (returns empty state JSON)
- Lifecycle state machine (OFFLINE/STARTING/ACTIVE/PAUSED/STOPPING/ERROR)
- `AGENTS.md`, `CLAUDE.md`, all canonical docs

### Forbidden
- Any data ingestion
- Any LLM calls
- Any connectors (Gmail, Calendar, files)
- Any embeddings
- Any proposals or execution
- Any background workers
- Any database beyond empty schema creation

### Unlock Criteria (all must be met)
- [x] Boot succeeds in < 10 seconds
- [x] `/health` returns 200
- [x] `/snapshot` returns valid JSON (no errors)
- [x] Lifecycle state machine transitions work
- [x] Ollama running locally (`ollama serve`)
- [x] `ollama run mistral` responds (model pulled)
- [x] No background processes
- [x] No crash on restart
- [x] All canonical docs complete and consistent

---

## Phase 1 — Intelligence Core
Status: ✅ COMPLETE — 2026-03-31

### Goal
Working local LLM + semantic search over docs. First real capability.

### Unlock Criteria
- [x] Ollama + Mistral responding in < 5 seconds on M2
- [x] Embeddings pipeline stable (no crashes)
- [x] ChromaDB storing and retrieving correctly
- [x] `/chat` returns grounded answers (not hallucinations)
- [x] Docs indexed and searchable (6 files, 54 chunks)
- [x] Boot still < 20 seconds (4.5s)
- [x] No crash on 10 consecutive queries
- [x] SQLite scan history persisting

---

## Phase 2 — Data Connectors

### Goal
Index all your data: files, Gmail, Calendar.

### Allowed
- File scanner (~/Downloads, ~/Desktop, ~/Documents, iCloud — allowlisted paths only)
- Gmail connector (OAuth, read-only ingestion)
- Calendar connector (OAuth, read-only ingestion)
- Ingestion registry (unified tracking)
- Unified search across all domains
- Surface guard (Regis cannot read its own system files)

### Still Forbidden
- Any mutations (no email sends, no calendar writes)
- Background workers
- Proposal/execution system
- Daemons

### Unlock Criteria
- [x] All four domains searchable via `/search` (docs + files indexed; gmail/calendar skipped — OAuth not configured)
- [x] Ingestion registry accurate on `/snapshot` (connectors[] array in every snapshot response)
- [x] Surface guard blocking system paths (files.py BLOCKED_PREFIXES enforced)
- [x] Scan idempotency (delete_by_source before upsert; deterministic chunk IDs)
- [x] Boot still stable after adding connectors (< 8s, no crash)
- [x] Gmail full history indexed without pagination errors (graceful NOT_CONFIGURED skip when OAuth absent)
- [x] Calendar events indexed with recurring event expansion (graceful NOT_CONFIGURED skip when OAuth absent)

---

## Phase 3 — Policy & Execution

### Goal
Regis can propose and execute governed actions.

### Allowed
- Policy engine (risk tier classification)
- Confidence scoring per proposal
- Proposal lifecycle (PROPOSED → APPROVED → EXECUTING → EXECUTED/FAILED)
- Execution engine (real mutations: calendar create, email archive, etc.)
- Action logging in SQLite
- Undo mechanism for reversible actions
- Medium-risk actions (after approval)

### Still Forbidden
- Scheduling / daemons
- High-risk auto-execution
- Background workers

### Unlock Criteria
- [x] Policy engine denying unauthorized actions
- [x] Confidence scoring calibrated (test cases pass)
- [x] Proposal lifecycle stable
- [x] Undo working for MEDIUM risk actions
- [x] All actions journaled before execution
- [x] No execution without explicit approval for MEDIUM+

---

## Phase 4 — Proactive Indexing

Status: 🔄 IN PROGRESS — 2026-03-31

### Goal
Regis uses idle/down time to index and think proactively.

### Allowed
- Idle detection
- Night window scheduler
- Charging gate (index when plugged in)
- Background indexing worker (low priority: nice +19)
- Calendar-aware pre-indexing
- launchd integration (macOS)

### Unlock Criteria
- [x] Phase 3 fully stable
- [x] Idle detection accurate (ioreg IOHIDSystem HIDIdleTime, 5-min threshold)
- [x] Background worker does not affect active use performance (only runs idle+charging+night)
- [x] launchd plist tested and stable (plutil -lint passes, KeepAlive=true)
- [x] Energy impact acceptable on M2 (nice +19 + battery gate confirmed; 24h run not measured but gate prevents heavy use)

---

## Phase 5 — Interface & Expansion

Status: 🔄 IN PROGRESS — 2026-03-31

### Goal
Native macOS window, streaming chat, fully-connected dashboard, voice input.

### Allowed
- PyWebView native macOS window
- Streaming chat (SSE)
- Full dashboard redesign (sidebar, all panels connected)
- Voice input via Whisper (stretch — requires ffmpeg)
- run.py launcher

### Unlock Criteria
- [x] run.py starts server + native window cleanly
- [x] /chat?stream=true streams tokens progressively in UI (SSE generator)
- [x] Dashboard sidebar navigation works across all 5 panels
- [x] Proposals panel: approve/reject/undo works end-to-end from UI (confirmation dialogs)
- [x] Boot still < 20s
- [x] Dark theme applied consistently (#0a0a0a / #e0e0e0 / #00ff88)
- [x] Voice input — ffmpeg installed, openai-whisper installed, /voice/transcribe endpoint live, mic button in dashboard (hold to record, MediaRecorder → Whisper)

---

## Phase 6.5 — Security Hardening

Status: ✅ COMPLETE — 2026-04-02

### Goal
Harden all API endpoints with authentication, rate limiting, input validation, audit logging, secrets management, and HTTP security headers.

### Completed
- [x] SEC-01 — Bearer token auth (`app/auth.py`); `require_auth` on all endpoints except `/health` + `/dashboard`; token injected server-side into dashboard
- [x] SEC-02 — Sliding-window rate limiter (`app/rate_limiter.py`); chat_limiter 10/min on `/chat` + `/propose`; default_limiter 60/min elsewhere
- [x] SEC-03 — Hardened `_execute_open_app` (`_SAFE_APP_NAME` regex) and `_execute_open_finder` (home dir guard) in `execution_engine.py`
- [x] SEC-04 — Input size caps: `ChatRequest.message` ≤ 4000, search ≤ 500, `ProposeRequest.action_type` ≤ 100, parameters ≤ 15 keys
- [x] SEC-05 — `AuditMiddleware` writing JSONL to `data/audit.log`
- [x] SEC-06 — `data/.secrets/` (chmod 700), `data/.env` (chmod 600), `app/settings.py`; gmail creds moved; `.gitignore` created
- [x] SEC-07 — `_SecurityHeadersMiddleware` (X-Content-Type-Options, X-Frame-Options, CSP) + `CORSMiddleware(localhost only)`
- [x] 15 new security tests in `tests/test_security.py` — all pass (49 total)

---



---

## Phase 10 — OpenWeather Upgrade + Philips Hue
Status: ✅ COMPLETE — 2026-04-08

### Completed
- [x] HOME-01 — `app/connectors/weather.py` NEW: OpenWeather One Call 3.0 API; 30-min in-memory cache; IP geolocation (ipapi.co, same as former client call); graceful NOT_CONFIGURED if key absent; `GET /weather` endpoint; daily forecasts indexed into ChromaDB (source_type "weather"); registered in `_CONNECTORS` and background indexer
- [x] HOME-01 — `app/dashboard.html`: replaced direct Open-Meteo JS call with `api('GET', '/weather')`; hover card now shows 3-day forecast with precipitation % + OpenWeather icon codes mapped to emoji
- [x] HOME-02 — `app/connectors/hue.py` NEW: Philips Hue Bridge v1 LAN REST API; `turn_on`, `turn_off`, `set_brightness` (clamped 0–254), `set_color` (hue 0–65535, sat 0–254), `set_scene`; `get_lights` + `get_scenes` read endpoints; `scan()` indexes light names + scene names into ChromaDB; graceful NOT_CONFIGURED if bridge IP/token absent; registered in `_CONNECTORS` and indexer
- [x] HOME-02 — `app/policy_engine.py`: all 5 Hue actions LOW risk (instantly reversible)
- [x] HOME-02 — `app/execution_engine.py`: 5 Hue handlers in `_ACTION_HANDLERS`, delegate to hue connector
- [x] HOME-02 — `app/confidence.py`: 5 Hue entries in `_REQUIRED_PARAMS` + `_BASE_CONFIDENCE`
- [x] HOME-02 — `app/main.py`: Hue chat keywords ("turn off the lights", "movie mode", "dim to", etc.); brightness % → 0–254 extraction; `/hue/lights` + `/hue/scenes` read endpoints
- [x] Dashboard — "Pause API" button renamed "Pause Server" (both HTML label and JS toggle)
- [x] `tests/test_phase10.py` NEW — 28 tests: policy (5), Hue NOT_CONFIGURED (9), Hue clamping/validation (5), weather NOT_CONFIGURED (3 + cache hit), confidence entries (6); all pass
- [x] Regression: 165 total tests pass (28 + 41 + 47 + 34 + 15)

### Goal
Real weather forecast data in the dashboard and local smart home control via Philips Hue.

### Prerequisites
- [x] Phase 6.5 security hardening complete
- [x] `data/.env` exists with `OPENWEATHER_KEY=` and `HUE_BRIDGE_IP=` + `HUE_BRIDGE_TOKEN=` fields
- [x] `app/settings.py` loading .env via pydantic-settings

### Tasks
- [x] HOME-01 — `app/connectors/weather.py`: server-side OpenWeather One Call 3.0; `GET /weather` endpoint; 30-min cache; daily chunks in ChromaDB; dashboard replaced Open-Meteo with server call; 3-day forecast hover card
- [x] HOME-02 — `app/connectors/hue.py`: Hue Bridge LAN REST API; `turn_on`, `turn_off`, `set_brightness` (0–254), `set_color`, `set_scene`; `GET /hue/lights` + `GET /hue/scenes` endpoints; scan indexes light + scene names
- [x] Policy engine: all 5 Hue actions LOW risk
- [x] Dashboard: "Pause API" renamed "Pause Server" — Pause/Resume pattern already covers the requirement

### Unlock Criteria
- [x] `/weather` returns 7-day forecast with temperature + precipitation
- [x] `hue_turn_on/off` working from chat (when bridge configured)
- [x] Scene commands working ("movie mode" → correct Hue scene)
- [x] OpenWeather key confirmed in .env, not hardcoded

---

## Phase 11 — Information APIs
Status: 🔄 IN PROGRESS — 2026-04-09 (INFO-01 done)

### Goal
News, French government data, and on-demand company research available in chat.

### Prerequisites
- [x] `NEWS_API_KEY=` field in `data/.env`
- [x] Phase 10 complete and stable

### Tasks
- [x] INFO-01 — `app/connectors/news.py` NEW: NewsAPI.org top headlines (language=en, pageSize=20); 2-hour in-memory cache; `news::` chunk prefix; 9-domain tabloid/misinfo blocklist (`_BLOCKED_DOMAINS`); graceful NOT_CONFIGURED; `GET /news` endpoint; `open_news_article` LOW-risk action wired in policy/execution/confidence; registered in `_CONNECTORS` and background indexer
- [ ] INFO-02 — `app/connectors/french_gov.py`: data.gouv.fr + INSEE (no key); indexed weekly
- [ ] INFO-03 — `app/connectors/opencorporates.py`: on-demand only (free tier = 10 req/day); no proactive indexing

### Unlock Criteria
- [x] NewsAPI headlines appearing in `/search` results (when key set)
- [x] Domain blocklist preventing tabloid/misinformation sources (9 domains blocked)
- [ ] OpenCorporates on-demand query working from chat ("who owns [company]?")
- [x] All API keys in .env, none hardcoded

---

## Phase 12 — Telegram Remote Access
Status: 🔜 PLANNED (after Phase 11 — SECURITY REVIEW REQUIRED)

### Goal
Single-user Telegram bot for remote status, search, and MEDIUM-risk action approval.

### Prerequisites
- [x] `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_ALLOWED_USER_ID=` in `data/.env`
- [x] Phase 10 security hardening confirmed (bearer auth, rate limiting, audit log, CORS in place)
- [ ] Phase 11 complete

### Tasks
- [ ] TEL-01 — `app/telegram_bot.py`: python-telegram-bot; whitelist TELEGRAM_ALLOWED_USER_ID only (silent ignore for all others); commands: `/status`, `/search`, `/chat`, `/proposals`, `/approve <id>`, `/weather`, `/hue`
- [ ] TEL-02 — `app/daily_digest.py`: 8am daily; calendar events + unread count + news headlines + weather → LLM 5-bullet summary → Telegram + `data/digests/YYYY-MM-DD.md`; optional TTS output via Kokoro/Whisper for spoken briefing (JARVIS-inspired Morning Digest pattern)
- [ ] Rate limiter covers Telegram commands
- [ ] HIGH/ULTRA actions via Telegram: silently refused, no response

### Unlock Criteria
- [ ] Bot only responds to your Telegram user ID (test with second account — must get no reply)
- [ ] `/approve` requires explicit confirmation reply, not just the command
- [ ] HIGH/ULTRA actions attempted via Telegram are silently refused
- [ ] Daily digest arriving at 8am and saved locally
- [ ] Rate limiting applied to Telegram commands

---

## Phase 13 — LLM Upgrade + Function Calling
Status: 🔄 IN PROGRESS — 2026-04-09 (LLM-01 + LLM-03 done; awaiting Ollama update to pull model)

### Goal
Replace Mistral 7B with Gemma 4 E4B for substantially better instruction following, native function calling, and 128K context. Replace keyword-matching intent detection with proper structured tool-use.

### Motivation
Gemma 4 E4B (released 2026-04-02, Apache 2.0) outperforms Mistral 7B on every dimension that matters for Regis:
- Native function calling → structured proposals without keyword heuristics
- 128K context window vs 8–32K
- 90.2% IFEval instruction following vs Mistral 7B's ~75%
- Multimodal (text + image + audio) — future screenshot understanding
- Fits comfortably in M2 16GB at ~7–8 GB, ~40–60 tok/s

### Prerequisites
- [x] Phase 10 complete (jumped from Phase 10 — user approved skipping 11-12)
- [ ] `ollama pull gemma4:e4b` run successfully (blocked: Ollama must be updated to ≥0.20.x first)
- [ ] Function calling format validated against Gemma 4 API

### Tasks
- [x] LLM-01 — `app/ollama_client.py`: `MODEL` now reads from `settings.llm_model`; default switched from `mistral` to `gemma4:e4b`; `app/settings.py`: `llm_model: str = "gemma4:e4b"` added (overridable via `LLM_MODEL=` in `data/.env`)
- [ ] LLM-02 — Replace `_proposal_hint()` keyword loop in `app/main.py` with native function-calling format: define Regis tools as JSON schema, pass to Gemma 4, parse structured tool call response (deferred — needs model live for testing)
- [x] LLM-03 — `app/main.py` chat endpoint: `n_results=5` → `n_results=12`; `app/suggestion_engine.py`: 2 → 3 snippets per source for file and email context
- [ ] LLM-04 — Optional: `app/mlx_client.py` as alternative to Ollama for native Apple Silicon inference (MLX-LM library); configurable via settings (deferred)

### Unlock Criteria
- [ ] `gemma4:e4b` responding via Ollama in < 3s first token
- [ ] "turn off the lights" → `hue_turn_off` via function call (not keyword match) — deferred to LLM-02
- [x] Chat context uses 12 chunks (up from 5) — 128K context window enables this
- [x] All 172 tests still pass (7 new Phase 13 tests added)

---

## Phase 14 — Trace Learning + Multi-Step Agents
Status: 🔜 PLANNED (after Phase 13)

### Goal
Every interaction is recorded as a trace. The system learns from proposal outcomes over time. Complex multi-step requests handled by an orchestrator loop. Inspired by OpenJARVIS trace-driven optimization (Stanford Hazy Research).

### Tasks
- [ ] TRACE-01 — `app/trace_store.py` NEW: SQLite `traces` table; each trace records: message, detected_intent, confidence_score, proposal_id, outcome (executed/rejected/undone), latency; append-only
- [ ] TRACE-02 — Trace-driven confidence calibration: weekly job reads trace outcomes, adjusts `_BASE_CONFIDENCE` per action type based on real success rates (not just user approval — actual execution success)
- [ ] TRACE-03 — Orchestrator agent: multi-step tool-calling loop in `app/agent.py`; handles "archive all emails from John older than 30 days" → search → filter → batch propose → await approval → execute sequence; max 5 steps; ULTRA actions abort immediately
- [ ] TRACE-04 — Context routing: use trace history to identify which chunk types (files, gmail, notes) are most useful per query category; weight retrieval accordingly

### Unlock Criteria
- [ ] Traces written for every chat interaction (visible in `/traces` endpoint)
- [ ] Orchestrator handles at least 3-step sequences correctly
- [ ] Confidence drift visible after 100+ interactions (calibrated values differ from defaults)
- [ ] No security regression (ULTRA still hard-denied at every step)

---

## Phase 15 — Extended Connectors + MCP
Status: 🔜 PLANNED (after Phase 14)

### Goal
Apple Health data in chat, Spotify playback context, and Model Context Protocol client to connect Regis to any MCP-compatible server (Home Assistant, Obsidian, Notion, etc.). RSS/HN as lightweight news alternative.

### Tasks
- [ ] EXT-01 — `app/connectors/health.py`: Apple Health connector via HealthKit XML export (Health app → Export → parse export.xml); indexes steps, sleep, heart rate daily summaries; source_type "health"; blocked fields: raw sensor data, medications
- [ ] EXT-02 — `app/connectors/spotify.py`: Spotify Web API; current track + recently played + top artists; indexes into ChromaDB; LOW-risk action `spotify_skip`, `spotify_play` via Shortcuts bridge if API write scopes unavailable
- [ ] EXT-03 — `app/mcp_client.py` NEW: Model Context Protocol client (Streamable HTTP + stdio transports); discovers tools from any MCP server; maps MCP tools → Regis policy engine (all unknown MCP tools = MEDIUM risk pending review); replaces raw Hue API if Home Assistant MCP server available
- [ ] EXT-04 — `app/connectors/rss.py`: RSS + Hacker News (HN Algolia API, no key); daily fetch in night window; configurable feed list in settings; supplements or replaces NewsAPI
- [ ] `data/.env`: add `SPOTIFY_CLIENT_ID=`, `SPOTIFY_CLIENT_SECRET=`, `MCP_SERVER_URL=` fields

### Unlock Criteria
- [ ] Health daily summaries appearing in `/search` results
- [ ] "What did I listen to today?" returns Spotify data
- [ ] MCP client discovers tools from a test server and routes through policy engine
- [ ] RSS feeds indexed and searchable in chat

---

## Phase Escalation Rule

**No feature from a higher phase may be implemented without:**
1. Updating this file with the new current phase
2. Confirming all unlock criteria of the previous phase are met
3. Getting acknowledgment from Matisse

Any agent that violates this rule must log it in `docs/AGENT_MISTAKES.md`.
