# Sovereign V3 — Master Roadmap
**Date:** 2026-04-02 | **Supersedes:** 2026-04-02_phase6-game-plan.md
**Author:** Claude (Cowork) | **Status:** Approved for implementation

Read AGENTS.md, PHASE_STATUS.md, and INVARIANTS.md before starting any task.
**Security Phase 6.5 is MANDATORY before any external API or remote access feature.**

---

## SECURITY ARCHITECTURE OVERVIEW

This needs to be understood upfront before implementing anything in Phase 7+.

### Current threat model
Regis binds to `127.0.0.1:8765` — localhost only, not exposed to your LAN or internet.
**That changes the moment you add:**
- A Telegram bot (it calls out, but if the bot is ever compromised or your user ID leaks, you have a remote control vector into your Mac)
- Any cloud sync or webhook
- Any time you ngrok / Tailscale / port-forward to access Regis from your phone

**Even on localhost today, there are threats:**
- Any other process on your Mac (malicious browser extension, infected app) can hit `localhost:8765` with no auth
- If prompt injection in web content tricks the LLM into emitting an `open_app` or `open_url` action, it auto-executes (LOW risk, no approval)
- `open_app` accepts app_name from natural language extraction with no allowlist validation

### The 8 security layers to implement

```
Layer 1 — API Token Auth         All endpoints except /health require Bearer token
Layer 2 — Rate Limiting          Per-IP + global limits; 429 on excess
Layer 3 — Subprocess Hardening   Allowlist for open_app; path guard for open_finder
Layer 4 — Input Size Caps        Chat ≤4000 chars, queries ≤500 chars, params ≤10 keys
Layer 5 — Audit Logging          All calls logged: timestamp, endpoint, IP, status code
Layer 6 — Secrets Management     No credentials in flat files; use .env + Keychain refs
Layer 7 — Remote Auth (Telegram) Single-user whitelist; READ actions only by default
Layer 8 — Security Headers       CSP + X-Frame-Options + X-Content-Type on all responses
```

---

## PHASE 6 — Bug Fixes + Voice (Session 1)
*Complete before anything else. These are unambiguous bugs.*

### BUG-01: `pkill -f ollama` kills ALL Ollama instances on shutdown
**File:** `app/main.py` — lifespan teardown
Track whether Regis spawned Ollama itself. Only kill that specific PID on shutdown.
```python
_ollama_pid: int | None = None
_ollama_started_by_us = False

# In /system/ollama/start — set _ollama_pid and _ollama_started_by_us = True
# In lifespan teardown — only kill if _ollama_started_by_us:
if _ollama_started_by_us and _ollama_pid:
    import os, signal
    try: os.kill(_ollama_pid, signal.SIGTERM)
    except ProcessLookupError: pass
```

### BUG-02: Voice endpoint is dead code — activate it
1. `brew install ffmpeg` (required by Whisper)
2. `pip install openai-whisper --break-system-packages`
3. Add to `app/main.py`:
```python
from app.voice import transcribe_audio
from fastapi import UploadFile, File

@app.post("/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)) -> dict:
    data = await audio.read()
    return transcribe_audio(data, filename=audio.filename or "audio.webm")
```
4. Add mic button to `dashboard.html` — uses `MediaRecorder` API, records on hold, sends WebM blob to `/voice/transcribe`, populates chat input with transcribed text.

### BUG-03: CURRENT_STATE.md stale Gmail note
Update "What Is Broken" to remove NOT_CONFIGURED Gmail claim.
Replace with: "Gmail OAuth credentials present in `data/` — run `/connectors/gmail/scan` to verify token validity."

### BUG-04: PHASE_STATUS.md stale
- Phase 4: mark `✅ COMPLETE — 2026-04-02`
- Phase 5: mark voice criterion as `[~] deferred — coded, awaiting ffmpeg+whisper` then `[x]` once BUG-02 is resolved. Mark Phase 5 `✅ COMPLETE` once voice is live.

### BUG-05: AGENTS.md endpoint budget drift
Update Complexity Budget: Phase 5 baseline = 24 endpoints. Phase 6 cap = 32. Phase 7+ requires an explicit budget increase in AGENTS.md.

### BUG-06: Stats top bar shows ERR / empty values
Three compounding issues:

**Fix A** — `r.json()` outside try/catch in `api()`:
```javascript
async function api(method, path, body) {
  try {
    const opts = { method, headers: {'Content-Type': 'application/json'} };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(BASE + path, opts);
    if (!r.ok) return {};
    return await r.json();  // awaited + inside try
  } catch { return {}; }
}
```

**Fix B** — No retry grace period. Show ERR only after 3 consecutive failures:
```javascript
let _statsFails = 0;
async function refreshStats() {
  const s = await api('GET', '/system/stats');
  if (s.cpu_percent == null && s.ram_percent == null) {
    if (++_statsFails >= 3) {
      document.getElementById('tb-cpu').textContent = 'ERR';
      document.getElementById('tb-ram').textContent = 'ERR';
    }
    return;
  }
  _statsFails = 0;
  // ... rest unchanged
}
```

**Fix C** — `psutil.cpu_percent(interval=0.2)` always returns 0.0 on first call (psutil quirk):
In `main.py` lifespan startup, seed the measurement:
```python
import psutil
psutil.cpu_percent()  # warm-up call — result discarded
```
Then change endpoint to use `interval=None` (instant, uses cached measurement).

---

## PHASE 6.5 — Security Hardening (MANDATORY — before Phase 7+)
*This phase unlocks all external API and remote access features.*

### SEC-01: API Token Authentication

**New file: `app/auth.py`**
```python
"""
API token authentication.
Token is generated on first run and stored at data/.api_token (chmod 600).
All endpoints except /health and /dashboard require:
    Authorization: Bearer <token>
The dashboard HTML is served with the token embedded so PyWebView works automatically.
"""
import secrets, os
from pathlib import Path
from fastapi import Header, HTTPException

TOKEN_PATH = Path(__file__).parent.parent / "data" / ".api_token"

def _load_or_create_token() -> str:
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(token)
    os.chmod(TOKEN_PATH, 0o600)  # owner read-only
    return token

API_TOKEN = _load_or_create_token()

async def require_auth(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
```

**In `main.py`:** Add `Depends(require_auth)` to all endpoints except `/health` and `/dashboard`.
```python
from fastapi import Depends
from app.auth import require_auth, API_TOKEN

# Exempt: /health, /dashboard
# Protected: everything else — add to each route:
@app.get("/snapshot", dependencies=[Depends(require_auth)])
```

**In `dashboard.html`:** The dashboard is served by FastAPI, so it can embed the token:
```python
# In dashboard() route — inject token into HTML before serving:
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    html = (Path(__file__).parent / "dashboard.html").read_text()
    html = html.replace("__REGIS_TOKEN__", API_TOKEN)
    return HTMLResponse(content=html)
```
In `dashboard.html`, add to the `api()` function:
```javascript
const REGIS_TOKEN = '__REGIS_TOKEN__';  // replaced server-side
async function api(method, path, body) {
  try {
    const opts = {
      method,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${REGIS_TOKEN}`,
      }
    };
    // ...
  }
}
```

### SEC-02: Rate Limiting

**New file: `app/rate_limiter.py`**
```python
"""Simple in-memory token bucket rate limiter."""
import time, threading
from collections import defaultdict
from fastapi import Request, HTTPException

class RateLimiter:
    def __init__(self, calls_per_minute: int):
        self._limit = calls_per_minute
        self._window = 60.0
        self._lock = threading.Lock()
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        with self._lock:
            timestamps = self._buckets[key]
            # Remove timestamps older than window
            self._buckets[key] = [t for t in timestamps if now - t < self._window]
            if len(self._buckets[key]) >= self._limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
            self._buckets[key].append(now)

# Two limiters: strict for expensive ops, lenient for reads
chat_limiter    = RateLimiter(calls_per_minute=10)
default_limiter = RateLimiter(calls_per_minute=60)
```
Apply to endpoints: `/chat` and `/propose` use `chat_limiter`, all others use `default_limiter`.

### SEC-03: Subprocess Argument Hardening

**In `app/execution_engine.py`:**

`_execute_open_app` — validate app_name:
```python
import re
_SAFE_APP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 \-_.]{0,63}$')

def _execute_open_app(params: dict) -> dict:
    app_name = params.get("app_name", "").strip()
    if not app_name or not _SAFE_APP_NAME.match(app_name):
        return {"success": False, "stub": False,
                "message": f"Invalid app name: '{app_name}'", "undo_data": None}
    # ... rest unchanged
```

`_execute_open_finder` — ensure path is under home directory:
```python
def _execute_open_finder(params: dict) -> dict:
    raw_path = params.get("path", "")
    path = Path(raw_path).expanduser().resolve()
    home = Path.home().resolve()
    try:
        path.relative_to(home)  # raises ValueError if not under home
    except ValueError:
        return {"success": False, "stub": False,
                "message": f"Path not under home directory: {raw_path}", "undo_data": None}
    # ... rest unchanged
```

### SEC-04: Input Size Caps

**In `main.py`:**
```python
class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000)
    use_web: bool = False

# In /search:
def search(q: str = Query(..., min_length=1, max_length=500), ...):

# In /propose:
class ProposeRequest(BaseModel):
    action_type: str = Field(..., max_length=100)
    parameters: dict = {}  # validated below

    @validator('parameters')
    def check_params(cls, v):
        if len(v) > 15:
            raise ValueError("Too many parameters")
        return v
```

### SEC-05: Audit Logging

**New file: `app/audit.py`**
```python
"""
Audit logger — every API call, proposal, and execution is logged.
Log format: JSONL at data/audit.log (one JSON object per line).
Rotated daily. Never logs secret values or full email bodies.
"""
import json, logging
from datetime import datetime, timezone
from pathlib import Path
from fastapi import Request, Response

AUDIT_LOG = Path(__file__).parent.parent / "data" / "audit.log"

async def audit_middleware(request: Request, call_next) -> Response:
    start = datetime.now(timezone.utc)
    response = await call_next(request)
    entry = {
        "ts": start.isoformat(),
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ip": request.client.host if request.client else "unknown",
    }
    with open(AUDIT_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return response
```
Register in `main.py`: `app.middleware("http")(audit_middleware)`

### SEC-06: Secrets Management

**Move all credentials out of flat `data/` files:**

1. Create `data/.secrets/` directory, `chmod 700`
2. Move `gmail_creds.json`, `gmail_token.json` → `data/.secrets/`
3. New API keys (OpenWeather, NewsAPI, Telegram, Hue) → `data/.env` (chmod 600):
```
OPENWEATHER_KEY=xxx
NEWS_API_KEY=xxx
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_ALLOWED_USER_ID=123456789
HUE_BRIDGE_IP=192.168.x.x
HUE_BRIDGE_TOKEN=xxx
```
4. Load in `app/settings.py`:
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    openweather_key: str = ""
    news_api_key: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_user_id: int = 0
    hue_bridge_ip: str = ""
    hue_bridge_token: str = ""

    class Config:
        env_file = "data/.env"

settings = Settings()
```

5. Add to `.gitignore`:
```
data/.env
data/.secrets/
data/.api_token
data/regis.db
data/chroma/
data/regis.stdout.log
data/regis.stderr.log
```

### SEC-07: Security Response Headers

**In `main.py`** — add middleware:
```python
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https://api.open-meteo.com https://ipapi.co; "
            "script-src 'unsafe-inline'; style-src 'unsafe-inline';"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)
# CORS: only allow localhost origin
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8765"])
```

### Phase 6.5 Unlock Criteria
- [ ] All endpoints except /health require valid Bearer token
- [ ] Rate limiter returns 429 correctly (test with rapid requests)
- [ ] open_app rejects path traversal and special chars
- [ ] open_finder rejects paths outside ~/
- [ ] Audit log populated on every request
- [ ] data/.env exists with chmod 600; data/.secrets/ exists with chmod 700
- [ ] 34 existing tests still pass + new security tests added
- [ ] Dashboard still works in PyWebView (token injection working)

---

## SESSION 2.5 — Bug Fixes + Suggestions Overhaul (April 3) ✅ COMPLETE

*Unplanned fixes discovered during Phase 6.5 follow-up testing. All 49 tests still pass.*

### CHAT-FIX: Streaming chat had no Authorization header
`sendChat()` in dashboard.html was calling `/chat?stream=true` without the `Authorization: Bearer` header added in SEC-01. Every streamed message was returning 401 silently. Fixed.

### GREETING-FIX: LLM injected file context into casual messages
`_build_prompt()` always injected 5 ChromaDB chunks even for "hey" / "hi" / "hello". Added `_GREETING_RE` pattern — casual messages now get a context-free prompt and the LLM responds naturally.

### SUGG-FIX: Suggestions showing 2010 calendar events + empty results
Three compounding bugs:
1. **ChromaDB `$gte` unsupported on strings** — the date filter `{"start": {"$gte": today}}` threw an exception that was silently caught, falling through to an unfiltered semantic query
2. **Wrong source_type** — suggestions filtered for `"files"` but ChromaDB stores `"file"` (no s) — file suggestions returned nothing
3. **Calendar had 747 events, 735 from 2010–2025** — calendar connector was fetching all history from 2010 → +5 years

Fixes:
- Added `get_where(where, limit)` and `delete_by_filter(where)` to `ChromaStore`
- Suggestions now: fetch all calendar chunks, filter upcoming in Python (no `$gte` on strings)
- Calendar connector changed to rolling window: past 30 days + next 90 days; wipes all calendar chunks on each scan via `delete_by_filter`
- 735 stale calendar events wiped immediately from index
- Corrected all `"files"` → `"file"` source_type references

### SUGG-FIX: Rich suggestion cards + screenshot smart prompts
- Suggestion items now show `{type, title, subtitle, text, source}` instead of raw 60-char snippet
- Calendar: title + "Today 2pm" / "Tomorrow" / "Mon Apr 6" formatted date
- Email: subject + sender name
- File: filename + shortened path
- **Screenshot smart prompts**: scans `~/Desktop` for `Screenshot*.png` files (macOS naming convention) — most recent 2 shown first. Clicking "Ask" fills chat with "What's in this screenshot: …?". Clicking "Open" reveals in Finder. No age/size logic — detection purely by filename pattern.
- `TYPE_ICONS` updated to include `screenshot: '🖼'`

### SCAN-FIX: Dashboard scan result showing "0" for calendar/gmail
`scanConn()` JS was reading `res.files_scanned || 0` for all connectors, but calendar/gmail return `items_indexed`. Rewrote with `_scanSummary(r)` helper that handles all three connector response formats + NOT_CONFIGURED + ERROR states.

### OLLAMA-FIX: Stop LLM button not stopping Ollama
psutil process iteration wasn't matching Ollama on macOS. Replaced with `pkill -x ollama` + `pkill -f "ollama serve"` fallback. Works reliably.

### CHIP-FIX: Source chips not clickable
Source chips at the bottom of chat responses are now clickable:
- `file`/`docs` type → `open_finder` proposal to reveal in Finder
- `calendar` → fills chat with "Tell me more about: [event]"
- `gmail` → fills chat with "Summarize the email: …"
Added `cursor: pointer` CSS + `title` tooltip with full path.

### CLEANUP-REVERT: Removed time-based file cleanup feature
A proactive cleanup feature (flagging files untouched > N days) was briefly added and immediately reverted. Time-based deletion suggestions are too blunt — many untouched files should never be deleted. Feature removed entirely from endpoint, CSS, HTML, and JS.

---

## PHASE 7 — Confidence + Intelligence Upgrade (Session 3) ✅ COMPLETE — 2026-04-03


### CONF-01: Confidence Scoring Overhaul (`app/confidence.py`)

**5 new dimensions (replace current 3-line algorithm):**

**1. Parameter quality scoring** — replace binary present/missing with quality check:
```python
def _param_quality_score(action_type: str, params: dict) -> float:
    """Returns 0.0–1.0 quality score for extracted parameters."""
    import re
    from pathlib import Path

    checks = {
        "app_name": lambda v: 0.9 if re.match(r'^[A-Za-z][A-Za-z0-9 ]{1,40}$', str(v)) else 0.3,
        "path":     lambda v: 1.0 if Path(str(v)).expanduser().exists() else 0.4,
        "url":      lambda v: 0.9 if re.match(r'^https?://[a-zA-Z0-9.-]+', str(v)) else 0.3,
        "query":    lambda v: 0.9 if len(str(v).split()) >= 2 else 0.6,
        "email_id": lambda v: 0.9 if re.match(r'^[0-9a-fA-F]{10,}$', str(v)) else 0.4,
    }
    required = _REQUIRED_PARAMS.get(action_type, [])
    if not required:
        return 1.0
    scores = []
    for p in required:
        if p not in params or params[p] is None:
            scores.append(0.0)   # missing
        elif p in checks:
            scores.append(checks[p](params[p]))
        else:
            scores.append(0.8)   # present but no quality check
    return sum(scores) / len(scores)
```
Replace flat `-0.15 per missing` with: `quality_score = _param_quality_score(action_type, params)` then `deduction = (1 - quality_score) * 0.30`

**2. Exponential decay on feedback** — replace flat 30-day window:
```python
import math

def _get_feedback_boost(action_type: str) -> float:
    rows = ...  # same query as before, include created_at
    if not rows: return 0.0
    now = datetime.now(timezone.utc)
    weights, weighted_approvals = [], []
    for approved, created_at_str in rows:
        days_ago = (now - datetime.fromisoformat(created_at_str)).days
        w = math.exp(-days_ago / 7.0)   # half-life ~5 days
        weights.append(w)
        weighted_approvals.append(w if approved else 0)
    total_w = sum(weights)
    approval_rate = sum(weighted_approvals) / total_w if total_w else 0
    # Recent rejection check (unweighted for last 3 days)
    recent_rejections = sum(1 for a, ts in rows if not a
                           and (now - datetime.fromisoformat(ts)).days <= 3)
    if recent_rejections > 0: return -0.12
    if total_w >= 2 and approval_rate >= 0.90: return 0.12
    if total_w >= 1 and approval_rate >= 0.75: return 0.07
    return 0.0
```

**3. Time-of-day context** — penalize file mutations during sleeping hours:
```python
def _time_context_modifier(action_type: str) -> float:
    hour = datetime.now().hour
    destructive = {"delete_file_trash", "move_email", "remove_email_label"}
    if action_type in destructive and (hour < 7 or hour >= 23):
        return -0.08   # nudge toward requiring approval during off-hours
    return 0.0
```

**4. Session activity boost** — if user chatted in last 10 min, they're present:
```python
def _session_activity_boost() -> float:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        row = conn.execute(
            "SELECT created_at FROM chat_messages ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            last = datetime.fromisoformat(row[0])
            mins_ago = (datetime.now(timezone.utc) - last).total_seconds() / 60
            if mins_ago < 10: return 0.05
    except Exception:
        pass
    return 0.0
```

**5. Updated `compute_confidence()`** combining all 5 dimensions:
```python
def compute_confidence(action_type, parameters, context=None) -> float:
    if action_type not in _BASE_CONFIDENCE: return 0.0
    base           = _BASE_CONFIDENCE[action_type]
    quality        = _param_quality_score(action_type, parameters)
    deduction      = (1 - quality) * 0.30
    context_boost  = min(len([v for v in (context or {}).values() if v]) * 0.05, 0.10)
    feedback_boost = _get_feedback_boost(action_type)
    time_modifier  = _time_context_modifier(action_type)
    activity_boost = _session_activity_boost()
    score = base - deduction + context_boost + feedback_boost + time_modifier + activity_boost
    return round(max(0.0, min(1.0, score)), 3)
```

**Updated `interpret()`** with 4 tiers:
```python
def interpret(score: float) -> str:
    if score < 0.30: return "low — ask clarifying question"
    if score < 0.50: return "medium-low — LOW actions only, params incomplete"
    if score < 0.70: return "medium — LOW actions only"
    return "high — MEDIUM approval path available"
```

### CONF-02: Scored Intent Detection (`app/main.py`)
Replace flat keyword loop with weighted scoring:
```python
def _detect_intent(message: str) -> tuple[str | None, float]:
    msg_lower = message.lower()
    scores: dict[str, float] = {}
    for keyword, action in _ACTION_KEYWORDS.items():
        if keyword in msg_lower:
            weight = min(len(keyword.split()) / 3.0, 1.0)  # longer = more specific
            scores[action] = max(scores.get(action, 0), weight)
    for pattern, action in _ACTION_PATTERNS:
        if pattern.search(message):
            scores[action] = max(scores.get(action, 0.55), 0.55)
    if not scores: return None, 0.0
    best = max(scores, key=scores.__getitem__)
    return best, scores[best]
```
Pass `detection_score` into `compute_confidence()` context dict.

### Phase 7 Unlock Criteria
- [x] 5 new confidence dimensions tested individually (47 tests in tests/test_confidence.py)
- [x] Regression: all 49 existing policy+security tests still pass (96 total)
- [x] New tests: open_app bad app_name < 0.80 ✓; good app_name ≥ 0.80 ✓
- [x] Scored intent detection: ambiguous "what time is it" → no match ✓; regex fallback → 0.55 ✓

---

## PHASE 8 — Suggestions Decoupling + Gmail/Calendar Live (Session 4) ✅ COMPLETE — 2026-04-03

### SUGG-01: Decouple Indexing from Suggestions

**Indexing gate (unchanged):** `idle + battery_ok` — runs all the time when conditions met
**Suggestions gate (new):** `idle + battery_ok + in_night_window` — true free time only

**New file: `app/suggestion_engine.py`**
```python
"""
Proactive suggestion engine — Phase 8.
Generates LLM-powered smart suggestions during free time only
(idle + battery_ok + in_night_window). Results cached in SQLite.
/suggestions reads from cache — never blocks on generation.
Cache TTL: 8 hours.
"""

# New SQLite table: suggestions(id TEXT, type TEXT, text TEXT, action_hint TEXT,
#                                generated_at TEXT)

class SuggestionEngine:
    def start() / stop() / get_suggestions() -> list[dict]

    def _should_generate() -> bool:
        return is_idle() and _battery_ok() and in_night_window()

    def _generate():
        """Query ChromaDB, ask Mistral to produce 3-5 natural prompts, cache in DB."""
        # Query for: upcoming events, recent files, unread count
        # Build LLM prompt: "Based on these snippets, suggest 3-5 actionable questions..."
        # Parse Mistral response into list of strings
        # Upsert into suggestions table with generated_at = now
        pass

    def get_suggestions() -> list[dict]:
        """Read from SQLite cache. Returns stale suggestions if cache hit (< 8h old)."""
        pass
```

Update `/suggestions` in `main.py` to read from cache instead of inline ChromaDB query.
Add `suggestion_engine.start()` / `suggestion_engine.stop()` to lifespan.

### GMAIL-01: Activate Gmail / Calendar Real Execution
1. Verify token: `./venv/bin/python -c "from app.connectors.gmail import _get_credentials; print(_get_credentials())"` — if None, run OAuth refresh
2. Wire `_execute_archive_email`: use `gmail.users().messages().modify()` to add ARCHIVED label, remove INBOX
3. Wire `_execute_mark_read`: remove UNREAD label
4. Wire `_execute_create_calendar_event`: `calendar.events().insert()` with title/start/end
5. Add integration test with a real throwaway Gmail account before testing on main account

### Phase 8 Unlock Criteria
- [x] `app/suggestion_engine.py` built: `get_cached()`, `_generate_and_cache()`, `maybe_refresh()`; hooked into background indexer during night window
- [x] `/suggestions` reads from cache first, falls back to inline ChromaDB when cold
- [x] `suggestions_cache` SQLite table created in `init_db()`
- [x] Gmail `archive_email`, `mark_read` wired with real API; graceful fallback if OAuth absent
- [x] Calendar `create_calendar_event` wired with real API; graceful fallback if OAuth absent
- [x] LLM stop/start button freeze fixed (polling + SIGKILL fallback)
- [ ] Suggestions cache verified populated after first real night-window idle cycle (requires overnight run)

---

## PHASE 9 — macOS Deep Integration

*Requires Phase 6.5 security complete.*

### MAC-01: Apple Contacts Connector
**New file: `app/connectors/contacts.py`**
- Read via `osascript` or `contacts` CLI tool
- Index: name, phone, email, company into ChromaDB with `contacts::` prefix
- Search: "find John's email", "what's my dentist's number"
- Risk: READ-ONLY, no writes in Phase 9
- New LOW-risk action: `open_contacts_card` (opens Contacts.app to specific person)

### MAC-02: Apple Notes Connector
**New file: `app/connectors/notes.py`**
- Read via AppleScript: `tell application "Notes" to get body of every note`
- Index: note title + body into ChromaDB with `notes::` prefix
- Notes contain personal content — surface guard: never index notes titled "passwords", "credentials", "ssh", "secret"
- New MEDIUM-risk action: `create_note`, `append_to_note`

### MAC-03: macOS AppleScript / Shortcuts
**New file: `app/automator.py`**
- Execute osascript for UI automation
- Actions:
  - `set_volume` (LOW) — `osascript -e 'set volume 5'`
  - `get_frontmost_app` (LOW, read-only)
  - `show_notification` (LOW) — macOS notification center
  - `run_shortcut` (MEDIUM) — trigger an iOS/macOS Shortcut by name
- All `osascript` commands go through an allowlist — no arbitrary script execution
- New policy_engine entries: all above added with appropriate risk tiers

### MAC-04: iOS Shortcuts Integration
- Incoming: Shortcuts can call `http://127.0.0.1:8765/chat` via "Get contents of URL" action (when on same WiFi as Mac)
- Outgoing: Regis can trigger named shortcuts via `osascript`
- Setup: create a "Regis Bridge" shortcut on iPhone that POSTs to localhost

### Phase 9 Unlock Criteria
- [ ] Contacts indexed and searchable
- [ ] Notes indexed (sensitive keyword filter working)
- [ ] Notification from Regis visible in macOS Notification Center
- [ ] `run_shortcut` tested with a real named shortcut
- [ ] All new osascript calls are in an allowlist (no arbitrary execution)

---

## PHASE 10 — Smart Home

*Requires Phase 6.5 security complete. Requires `data/.env` with credentials.*

### HOME-01: OpenWeather API Upgrade
**Replace current Open-Meteo** (no-key, limited) with **OpenWeather 3.0 One Call API** (free tier, 1000 calls/day):
- Current weather + 7-day forecast + precipitation + UV index + air quality
- Store API key in `data/.env` as `OPENWEATHER_KEY`
- New endpoint: `GET /weather` (replaces client-side call in dashboard)
- Dashboard fetches from Regis, not directly from OpenWeather (avoids key exposure in JS)
- Add to ChromaDB: daily weather summaries with `weather::` prefix for context

### HOME-02: Philips Hue Integration (Local LAN)
**New file: `app/connectors/hue.py`**
- Hue Bridge REST API: `http://<bridge_ip>/api/<token>/` — LAN-only, no internet required
- Discovery: run `python -c "import socket; ..."` or use `upnp` discovery, store bridge IP in `.env`
- Actions (all through policy engine):
  - `hue_turn_on` / `hue_turn_off` (LOW — instant, reversible)
  - `hue_set_brightness` (LOW)
  - `hue_set_color` (LOW)
  - `hue_set_scene` (LOW — named scenes like "Reading", "Movie", "Wake up")
- Chat: "turn off the lights", "set bedroom to warm white", "dim everything to 20%"
- Scene shortcuts: "movie mode", "focus mode", "goodnight" — maps to preset Hue scenes

### HOME-03: Google Home / Nest (Optional — complex)
- Use Google's SDM (Smart Device Management) API for Nest Thermostat / Nest Protect
- OAuth required — same infrastructure as Gmail (add to existing Google creds)
- Actions: `get_thermostat_temp`, `set_thermostat` (MEDIUM)
- **Note:** This only works for Nest devices, not Google Home speakers. Casting music = different API (Cast SDK). Evaluate whether this is worth the OAuth complexity.

### Phase 10 Unlock Criteria
- [ ] OpenWeather key in .env, `/weather` endpoint returning forecast
- [ ] Hue bridge discovered and token stored in .env
- [ ] `hue_turn_on/off` working from chat ("turn off the lights")
- [ ] Scene commands working ("movie mode" → correct Hue scene)
- [ ] Hue actions rate-limited (avoid hammering bridge)

---

## PHASE 11 — Information APIs

*All keys in `data/.env`. All responses zero-trust (untrusted content markers).*

### INFO-01: NewsAPI
**New file: `app/connectors/news.py`**
- API: NewsAPI.org (free tier = 100 requests/day, top headlines + search)
- Filters (hardcoded defaults, configurable in `.env`):
  - Sources: reputable outlets only (BBC, Reuters, Le Monde, Les Echos, etc.)
  - Language: fr + en
  - Topics: none by default (let Regis filter based on user questions)
- Indexing: run once daily during night window, store headlines in ChromaDB `news::` prefix
- Chat: "what's in the news today?", "any news about [topic]?"
- New action: `open_news_article` (LOW — opens URL in Arc)
- **Warning:** Set `BLOCKED_DOMAINS` list for tabloids/misinformation sources

### INFO-02: French Government Data (data.gouv.fr + INSEE)
**New file: `app/connectors/french_gov.py`**
- data.gouv.fr: public datasets API, no key required
- INSEE: statistics API, no key required
- Use cases: local election data, economic statistics, public services info
- These are static/slow-changing datasets — index weekly, not daily
- Parse JSON responses manually (no library dependency)

### INFO-03: OpenCorporates (Business Intelligence)
**New file: `app/connectors/opencorporates.py`**
- API: opencorporates.com (free tier = 10 requests/day; paid = more)
- Use cases: "who owns [company]?", "look up [business]", company filings
- Don't index proactively — query on-demand from chat only (avoid burning free quota)
- Risk: READ-ONLY. Results are UNTRUSTED public data.

### INFO-04: Alpha Vantage (Market Data) — Optional
- Free tier: 25 API calls/day
- Stocks, FX, crypto prices + basic fundamentals
- Only useful if you actively track specific assets
- Store watched symbols in `.env` as `ALPHA_VANTAGE_SYMBOLS=AAPL,BTC`

### Phase 11 Unlock Criteria
- [ ] NewsAPI returning headlines and they're appearing in search results
- [ ] Domain blocklist working (test with a blocked domain)
- [ ] data.gouv.fr connector parsing correctly
- [ ] OpenCorporates on-demand query working from chat
- [ ] All API keys in .env, none hardcoded

---

## PHASE 12 — Remote Access (Telegram Bot)

*MUST be Phase 6.5 complete before starting this. Security is non-negotiable here.*

### TEL-01: Telegram Bot with Strict Auth

**New file: `app/telegram_bot.py`**
- Uses `python-telegram-bot` library
- **Authentication first:** All messages from any user ID other than `TELEGRAM_ALLOWED_USER_ID` are silently ignored (no response, no error — don't reveal the bot exists)
- Commands:
  - `/status` → returns `/snapshot` summary (chunk count, last scan, Ollama status)
  - `/search <query>` → runs `/search`, returns top 3 results
  - `/chat <message>` → sends to `/chat`, returns Mistral response
  - `/proposals` → lists PROPOSED items awaiting approval
  - `/approve <id>` → approves a MEDIUM proposal (requires confirmation reply)
  - `/weather` → current weather
  - `/hue <command>` → Hue controls (if Phase 10 done)
- **What Telegram cannot do:**
  - No HIGH or ULTRA actions ever
  - No file deletion without explicit `/confirm delete <id>` reply within 60 seconds
  - No credential access
  - No direct bash or osascript execution
- Runs as a daemon thread (alongside background indexer and suggestion engine)
- If bot token not configured, thread exits cleanly on start

### TEL-02: Daily Digest via Telegram
**New file: `app/daily_digest.py`**
- Triggered by launchd job at 8:00am daily
- Queries: today's calendar events, unread email count (if Gmail configured), overnight news headlines, weather for the day
- Sends Mistral-generated 5-bullet summary to Telegram
- Also saves to `data/digests/YYYY-MM-DD.md` locally

### Phase 12 Unlock Criteria
- [ ] Bot only responds to your Telegram user ID (test with a second account — must get no response)
- [ ] `/approve` requires explicit confirmation reply, not just the command
- [ ] HIGH/ULTRA actions attempted via Telegram are silently refused
- [ ] Daily digest sent at 8am and saved locally
- [ ] Rate limiting: Telegram commands also go through rate limiter

---

## PHASE 13 — Advanced / Experimental

*Low priority. Do only if the above phases are stable.*

### ADV-01: Hybrid Search (BM25 + Semantic)
Add `rank-bm25` (pure Python) for keyword index alongside ChromaDB.
Merge at query time via reciprocal rank fusion. Especially valuable for searching by name/date/email subject.

### ADV-02: SEC / EDGAR
- `sec-api` or direct EDGAR API (no key needed for basic access)
- For publicly traded companies: 10-K, 10-Q filings
- High value if tracking specific companies

### ADV-03: NASA APIs
- APOD (Astronomy Picture of the Day) — trivial, just fun
- Near-Earth Objects (asteroid tracking) — genuinely interesting data
- No key needed for most endpoints

### ADV-04: Social Media (Read-Only)
- Reddit: via `praw` (free, no key for public content)
- Twitter/X: API access is now heavily restricted/paid — skip unless worth the cost
- Risk: these are read-only but the content is untrusted and can contain injection attempts — existing zero-trust handling required

### ADV-05: Flightradar24 / Flight Tracking
- Flightradar24 has no public API; scraping is against ToS
- Use **AviationStack** (free tier = 100 requests/month) or **OpenSky Network** (free, open data)
- Use cases: "is my flight delayed?", "track [flight number]"
- Niche but genuinely useful for travel

---

## NOT BUILDING (With Reasoning)

| Feature | Why Not |
|---------|---------|
| Banking APIs (Plaid, etc.) | Catastrophic risk if compromised. Every banking action = HIGH/ULTRA. The security overhead is disproportionate to the value for a personal assistant. |
| Cadastre | Very specialized French land registry. Low daily utility. |
| Full social media write access | Reputation damage risk if LLM makes an error. The policy engine would block everything as ULTRA anyway. |
| OpenAI / Claude API | Violates zero-cost principle from AGENTS.md |
| Any cloud sync of `data/` | Data sovereignty is the whole point of Sovereign V3 |

---

## IMPLEMENTATION ORDER FOR CLAUDE CODE

```
Session 1   ✅ Phase 6   (BUG-01 through BUG-06) — 2026-04-02
Session 2   ✅ Phase 6.5 (SEC-01 through SEC-07) — SECURITY HARDENING — 2026-04-02
Session 2.5 ✅ Bug fixes + suggestions overhaul + calendar cleanup — 2026-04-03
Session 3   ✅ Phase 7   (CONF-01, CONF-02) — CONFIDENCE + INTELLIGENCE — 2026-04-03
Session 4   ✅ Phase 8   (SUGG-01, GMAIL-01) — SUGGESTIONS + GMAIL LIVE — 2026-04-03
Session 5   → Phase 9   (MAC-01 Contacts, MAC-02 Notes, MAC-03 AppleScript) ← NEXT
Session 6   → Phase 10  (HOME-01 OpenWeather, HOME-02 Hue)
Session 7   → Phase 11  (INFO-01 News, INFO-02 French Gov, INFO-03 OpenCorporates)
Session 8   → Phase 12  (TEL-01 Telegram, TEL-02 Daily Digest)
Session 9+  → Phase 13  (Hybrid search, ADV features as wanted)
```

**Hard rules:**
- Phase 6.5 (Security) MUST be complete before Session 5+
- Every session: update CHANGELOG.md + CURRENT_STATE.md
- Every new connector: graceful NOT_CONFIGURED skip (same pattern as Gmail)
- Every new action type: add to policy_engine.py allow-list with correct risk tier
- Every new action type: add to confidence.py _BASE_CONFIDENCE and _REQUIRED_PARAMS
- Every new secret: goes in data/.env, never hardcoded
- New phase = new PHASE_STATUS.md entry with explicit unlock criteria

---

## RISK TIERS FOR ALL NEW ACTIONS

| Action | Tier | Reasoning |
|--------|------|-----------|
| open_contacts_card | LOW | Opens app, no mutation |
| show_notification | LOW | Read-only side effect |
| set_volume | LOW | Instantly reversible |
| hue_turn_on/off | LOW | Instantly reversible |
| hue_set_brightness | LOW | Instantly reversible |
| hue_set_color | LOW | Instantly reversible |
| hue_set_scene | LOW | Instantly reversible |
| open_news_article | LOW | Opens URL |
| get_thermostat_temp | LOW | Read-only |
| create_note | MEDIUM | Creates data, reversible |
| append_to_note | MEDIUM | Modifies data, reversible |
| run_shortcut | MEDIUM | Executes arbitrary automation |
| set_thermostat | MEDIUM | Physical effect |
| send_telegram_message | MEDIUM | Sends external message |
| delete_note | HIGH | Data loss |
| post_to_social | ULTRA | Reputational risk — hard deny |
| access_banking | ULTRA | Financial — hard deny |
