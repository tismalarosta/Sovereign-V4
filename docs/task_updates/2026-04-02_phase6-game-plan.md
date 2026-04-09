# Sovereign V3 — Phase 6 Game Plan
**Date:** 2026-04-02
**Author:** Claude (Cowork)
**Status:** Approved for implementation

This document is a complete action plan for the next development session with Claude Code.
Read AGENTS.md, PHASE_STATUS.md, and INVARIANTS.md before starting any task below.

---

## Priority 0 — Bug Fixes (Do First, No Exceptions)

### BUG-01: `pkill -f ollama` kills ALL Ollama instances on shutdown
**File:** `app/main.py` — lifespan teardown
**Problem:** `subprocess.run(["pkill", "-f", "ollama"])` will kill any Ollama process running on the machine, not just the one Regis started. If anything else uses Ollama, this nukes it.
**Fix:** Track the PID of `ollama serve` when Regis starts it, and only kill that PID on shutdown. If Ollama was already running when Regis started, don't kill it at all.
```python
# In lifespan startup — detect if ollama was pre-existing:
_ollama_started_by_us = False  # set True only if we spawn it

# In lifespan shutdown:
if _ollama_started_by_us and _ollama_pid:
    os.kill(_ollama_pid, signal.SIGTERM)
```

### BUG-02: Voice endpoint is dead code
**File:** `app/voice.py` exists, `app/main.py` never imports or registers it
**Problem:** `POST /voice/transcribe` endpoint is written but unreachable. Whisper not installed.
**Fix:**
1. `pip install openai-whisper --break-system-packages` (ffmpeg must be installed first: `brew install ffmpeg`)
2. Add to `main.py`:
```python
from app.voice import transcribe_audio
from fastapi import UploadFile, File

@app.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)) -> dict:
    data = await audio.read()
    return transcribe_audio(data, filename=audio.filename or "audio.webm")
```
3. Add mic button to `dashboard.html` — MediaRecorder API, sends WebM blob to `/voice/transcribe`, puts result in chat input

### BUG-03: CURRENT_STATE.md says Gmail is NOT_CONFIGURED — it's configured
**File:** `docs/CURRENT_STATE.md` line 67
**Fix:** Update "What Is Broken" section: remove the NOT_CONFIGURED Gmail note, replace with "Gmail OAuth credentials present in data/ — run `/connectors/gmail/scan` to verify token is still valid"

### BUG-04: PHASE_STATUS.md is stale
**File:** `docs/PHASE_STATUS.md`
**Problem:** Phase 4 still shows `🔄 IN PROGRESS` and Phase 5 shows `🔄 IN PROGRESS` — both are functionally complete
**Fix:** Update Phase 4 to `✅ COMPLETE — 2026-04-02`. Update Phase 5 voice criterion to `[~] Voice input — deferred; endpoint coded, awaiting ffmpeg+whisper install`. Mark Phase 5 as complete once BUG-02 is resolved.

### BUG-05: AGENTS.md documents a 12-endpoint hard limit — there are 24 endpoints
**File:** `AGENTS.md` — Complexity Budget section
**Problem:** Phase 1-2 budget said "Max 12 API endpoints." That constraint was Phase 1-2 specific but was never updated when Phase 5 expanded.
**Fix:** Update the Complexity Budget section to reflect the current reality: document the 24-endpoint count as the Phase 5 baseline, and set a Phase 6 cap (e.g. 30 max) to prevent unlimited sprawl.

### BUG-06: Stats top bar shows ERR / empty values (CPU, RAM, battery)
**Files:** `app/dashboard.html` — `api()` helper + `refreshStats()` / `app/main.py` — `/system/stats`
**Root causes (3):**

**Cause A — `r.json()` outside the try/catch:**
```javascript
async function api(method, path, body) {
  try {
    const r = await fetch(BASE + path, opts);
    return r.json();   // ← NOT in the try block — if server returns 500 HTML, this throws
  } catch { return {}; }
}
```
If the server returns any non-JSON body (500 error page, timeout), `r.json()` throws OUTSIDE the catch. The `api()` call rejects instead of returning `{}`, and `refreshStats()` dies silently.

**Fix A:** Move `r.json()` inside the try block:
```javascript
async function api(method, path, body) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(BASE + path, opts);
    if (!r.ok) return {};
    return await r.json();   // ← awaited AND inside try
  } catch { return {}; }
}
```

**Cause B — No retry grace period:**
One failed call immediately shows ERR. On startup the server might still be initializing.

**Fix B:** Track consecutive failures, only show ERR after 3 in a row:
```javascript
let _statsFails = 0;
async function refreshStats() {
  const s = await api('GET', '/system/stats');
  if (s.cpu_percent == null && s.ram_percent == null) {
    _statsFails++;
    if (_statsFails >= 3) {
      document.getElementById('tb-cpu').textContent = 'ERR';
      document.getElementById('tb-ram').textContent = 'ERR';
    }
    return;
  }
  _statsFails = 0;  // reset on success
  // ... rest of update
}
```

**Cause C — `psutil.cpu_percent(interval=0.2)` blocks 200ms synchronously:**
FastAPI runs sync endpoints in a thread pool, so this is safe, but it means the endpoint always takes ≥200ms. Fine to keep, but change to `interval=None` (uses last cached measurement, instant) and call `psutil.cpu_percent()` without interval to pre-warm on startup.

**Fix C:** In `main.py` lifespan startup, call `psutil.cpu_percent()` once to seed the measurement:
```python
import psutil
psutil.cpu_percent()   # warm up — first call always returns 0.0 otherwise

# Then in the endpoint, use interval=None (uses cached value):
"cpu_percent": psutil.cpu_percent(interval=None),
```

---

## Priority 1 — Confidence Scoring Overhaul

**File:** `app/confidence.py`

The current scorer is deterministic base + param deductions + a thin feedback layer. It doesn't account for context that actually matters: what time it is, how recently the user ran this action, whether the extracted params are high-quality or just "something was found."

### New scoring dimensions to add:

**1. Parameter quality scoring** (replace binary present/missing)
Currently: missing param → -0.15. That's it.
Replace with a quality check per param type:
- `app_name`: is it a known macOS app name? (+0.05 bonus if yes, -0.10 if single char/garbage)
- `path`: does the path actually exist on disk? (+0.05 if yes, -0.10 if not)
- `url`: is it a valid URL with a real domain? (+0.05 if yes)
- `query`: is it > 3 words? (+0.03 if yes)
- `email_id`: is it a valid Gmail message ID format?

**2. Recency boost** (reward recently approved patterns)
The current feedback window is 30 days flat — no decay. A rejection from 29 days ago weighs the same as one from yesterday.
Replace with **exponential decay**:
```python
# Weight each feedback event by e^(-days_ago / 7)
# Recent approvals have strong weight, old ones fade
weight = math.exp(-days_ago / 7.0)
weighted_approval_rate = sum(w for approved, w) / sum(all w)
```

**3. Time-of-day context**
Don't auto-execute file operations at 2am if the user is likely asleep.
```python
# In compute_confidence():
hour = datetime.now().hour
if action_type in ("delete_file_trash", "move_email") and (hour < 7 or hour > 23):
    score -= 0.08   # nudge toward requiring approval during off-hours
```

**4. Session activity boost**
If the user has been actively chatting in the last 10 minutes, they're present and watching — boost confidence slightly for LOW actions.
```python
# Check last chat message timestamp in SQLite
last_active_mins_ago = _get_last_activity_minutes()
if last_active_mins_ago < 10:
    score += 0.05  # user is present
```

**5. Parameter count completeness ratio**
Instead of flat -0.15 per missing param, use a ratio:
```python
completeness = len(present_params) / max(len(required_params), 1)
deduction = (1 - completeness) * 0.25   # max 0.25 if nothing provided
```

**Updated `interpret()` function** — add a fourth tier:
```python
def interpret(score: float) -> str:
    if score < 0.30: return "low — ask clarifying question"
    if score < 0.50: return "medium-low — LOW actions only, params incomplete"
    if score < 0.70: return "medium — LOW actions, watch for confirmation"
    return "high — MEDIUM approval path available"
```

---

## Priority 2 — Decouple Indexing from Suggestions

**Current problem:** Both background indexing and suggestions use the same `BackgroundIndexer`. Suggestions are generated on-demand (ChromaDB query on every `/suggestions` request). There's no concept of "free time" vs "idle time."

**Goal:**
- **Indexing**: run whenever `idle + battery_ok` — this is already correct, keep it
- **Suggestions**: generate proactively only during `idle + battery_ok + night_window` (true free time), cache results in SQLite, serve from cache on `/suggestions`

### Changes needed:

**1. New `app/suggestion_engine.py`**
```python
"""
Proactive suggestion engine — Phase 6.
Generates smart prompts during free time (idle + battery_ok + night_window).
Suggestions are cached in SQLite and served stale until refreshed.
Runs as a second daemon thread alongside BackgroundIndexer.
"""

# Cache table: suggestions(id, type, text, action_hint, generated_at)
# TTL: 6 hours — stale suggestions still serve, just don't feel fresh

class SuggestionEngine:
    def start() / stop() / get_suggestions() -> list[dict]

    def _generate():
        # Only runs during free time
        if not (is_idle() and _battery_ok() and in_night_window()):
            return
        # Query ChromaDB for upcoming events, unread emails, recent files
        # Use Mistral to generate 3-5 natural language suggestions
        # Cache in SQLite with generated_at timestamp
```

**2. Update `app/main.py` `/suggestions` endpoint**
```python
# Instead of querying ChromaDB directly, read from suggestion cache:
from app.suggestion_engine import suggestion_engine

@app.get("/suggestions")
def suggestions() -> dict:
    cached = suggestion_engine.get_suggestions()  # reads from SQLite cache
    if not cached:
        # Fallback: generate inline if cache is empty (cold start)
        return _generate_fallback_suggestions()
    return {"suggestions": cached}
```

**3. Update lifespan in `main.py`**
```python
suggestion_engine.start()   # add alongside indexer.start()
# in teardown:
suggestion_engine.stop()
```

**4. What suggestions should look like when LLM-generated**
Instead of keyword-matched ChromaDB snippets (current), use Mistral to actually generate actionable prompts:
- "You have 3 files modified today in Downloads — want me to summarize them?"
- "Your next calendar event is [title] — want me to pull context?"
- "You haven't indexed in 48 hours — force index now?"

---

## Priority 3 — Gmail / Calendar Activation

Both connectors are fully coded. The OAuth infrastructure exists. Just needs activation.

### Steps:
1. **Verify credentials**: check `data/gmail_creds.json` and `data/gmail_token.json` exist and token is valid
   ```bash
   ./venv/bin/python -c "
   from app.connectors.gmail import _get_credentials
   creds = _get_credentials()
   print('Valid:', creds is not None and creds.valid)
   "
   ```
2. **If token expired**: run the OAuth refresh flow
   ```bash
   ./venv/bin/python scripts/oauth_setup.py   # create this if it doesn't exist
   ```
3. **Wire real execution handlers** in `app/execution_engine.py`:
   - `_execute_archive_email` — use `gmail.users().messages().modify()` to add ARCHIVED label, remove INBOX
   - `_execute_mark_read` — `modify()` to remove UNREAD label
   - `_execute_move_email` — `modify()` with target label
   - `_execute_create_calendar_event` — `calendar.events().insert()` with title/start/end
4. **Test each handler** with a real test email/event before marking EXECUTED

---

## Priority 4 — Intent Detection Improvement

**Current problem:** `_ACTION_KEYWORDS` is a flat dict of 30+ string literals. `_ACTION_PATTERNS` is 5 regexes. This will get unmaintainable as action types increase, and it currently misses natural variations.

**Fix — two-pass scoring approach:**

Replace the keyword loop with a scored intent function:
```python
def _detect_intent(message: str) -> tuple[str | None, float]:
    """
    Returns (action_type, score) where score is 0.0–1.0.
    Uses weighted keyword matching + regex bonus.
    """
    msg_lower = message.lower()
    scores: dict[str, float] = {}

    for keyword, action in _ACTION_KEYWORDS.items():
        if keyword in msg_lower:
            # Weight by keyword specificity (longer = more specific = higher weight)
            weight = min(len(keyword.split()) / 3.0, 1.0)
            scores[action] = max(scores.get(action, 0), weight)

    for pattern, action in _ACTION_PATTERNS:
        if pattern.search(message):
            scores[action] = max(scores.get(action, 0.6), 0.6)

    if not scores:
        return None, 0.0

    best_action = max(scores, key=scores.__getitem__)
    return best_action, scores[best_action]
```

Then pass the detection confidence into `compute_confidence()` as a context item:
```python
action_type, detection_score = _detect_intent(message)
params = _extract_action_params(action_type, message)
confidence = compute_confidence(
    action_type, params,
    context={"detection_score": detection_score, ...}
)
```

This means if detection was weak (0.4), confidence gets less of a boost than if it was strong (0.9). Much more honest.

---

## Priority 5 — Phase 6 Features (New Capabilities)

These should be gated behind a new Phase 6 entry in PHASE_STATUS.md before starting.

### P6-01: Notion Integration (read + write)
**Connector:** `app/connectors/notion.py`
- Read: pages, databases, blocks → index into ChromaDB with `notion::` source prefix
- Write: create pages, append to pages (MEDIUM risk), update existing blocks
- Use official Notion API (free tier, integration token in data/)
- Execution handlers: `create_notion_page`, `append_notion_block` (both MEDIUM)

### P6-02: Telegram Bot (mobile control)
**New module:** `app/telegram_bot.py`
- Lets you interact with Regis from your phone via Telegram
- Receive: `/search [query]`, `/chat [message]`, `/status`, `/proposals`
- Send: proposal approval/rejection from mobile
- Bot token stored in `data/telegram_token.txt` (never committed)
- Risk: bot must authenticate — only respond to your Telegram user ID
- Runs as a third daemon thread (or separate process via launchd)

### P6-03: Daily Digest (proactive, scheduled)
**New module:** `app/daily_digest.py`
**Trigger:** launchd job at 8am daily
- Queries ChromaDB for: events today, unread email count, recent file changes
- Uses Mistral to generate a 3-5 bullet plain-English summary
- Saves digest to `data/digests/YYYY-MM-DD.md`
- Optionally sends via Telegram bot if configured
- Risk tier: LOW (read-only, local file write)

### P6-04: Hybrid Search (BM25 + semantic)
**File:** `app/chroma_store.py` + new `app/bm25_index.py`
**Problem:** Pure semantic search misses exact keyword matches (names, file paths, dates)
**Fix:** Add BM25 keyword index alongside ChromaDB. At query time, merge scores:
```python
semantic_results = store.query(embedding, n_results=10)
bm25_results = bm25_index.search(query, n_results=10)
merged = reciprocal_rank_fusion(semantic_results, bm25_results)[:5]
```
Library: `rank-bm25` (pure Python, no new system deps)

### P6-05: Slack Integration (read-only first)
**Connector:** `app/connectors/slack.py`
- Read channels, DMs, threads → index with `slack::` prefix
- Bot token in `data/slack_token.txt`
- Start read-only (index messages, search from chat)
- Write (send message) = MEDIUM risk, Phase 6.1+

---

## Implementation Order for Claude Code

Run these in order. Complete each before starting next. Update CHANGELOG.md + CURRENT_STATE.md after every task.

```
Session 1 (Bug fixes + Voice):
  [ ] BUG-01: Fix ollama shutdown (PID tracking)
  [ ] BUG-02: Install ffmpeg + whisper, register /voice/transcribe, add mic button to dashboard
  [ ] BUG-03: Fix CURRENT_STATE.md Gmail stale note
  [ ] BUG-04: Update PHASE_STATUS.md
  [ ] BUG-05: Update AGENTS.md endpoint budget

Session 2 (Confidence + Intent):
  [ ] Priority 1: Confidence scoring overhaul (all 5 dimensions)
  [ ] Priority 4: Intent detection improvement (scored matching)
  [ ] Run 34 existing tests + add new confidence tests

Session 3 (Suggestions decoupled):
  [ ] Priority 2: Create app/suggestion_engine.py
  [ ] Update /suggestions endpoint to read from cache
  [ ] Update main.py lifespan to start/stop suggestion_engine
  [ ] Test: verify indexing still runs all the time, suggestions only during night window

Session 4 (Gmail/Calendar live):
  [ ] Priority 3: Verify OAuth, wire real execution handlers, test

Session 5+ (Phase 6 features):
  [ ] Update PHASE_STATUS.md to add Phase 6
  [ ] P6-01 Notion, P6-02 Telegram, P6-03 Daily Digest, P6-04 Hybrid Search, P6-05 Slack
```

---

## What NOT to change

- `app/policy_engine.py` — deny-by-default is correct, don't add new risk tiers
- `app/proposal_manager.py` — lifecycle is solid, don't touch
- `app/lifecycle.py` — state machine is correct
- `data/regis.db` schema — only ADD tables, never drop or alter existing ones
- The governance docs (AGENTS.md, INVARIANTS.md) — route changes through Claude (Cowork) first

---

## Tests to write alongside each change

- BUG-01: test that shutdown doesn't kill a pre-existing ollama PID
- Priority 1: test each new confidence dimension independently; regression test all 34 existing cases still pass
- Priority 2: test suggestion cache hit/miss, test free-time gate (mock is_idle + in_night_window)
- Priority 4: test scored intent detection for ambiguous inputs
- Priority 3 (Gmail): integration test with a real sandboxed Gmail account before prod
