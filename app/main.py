"""
Sovereign V3 — Regis
Phase 5: Interface & Expansion — glassmorphism UI, chat history, OS actions, web search.
"""

import json
import re
import sqlite3
import subprocess
import uuid
from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from app.lifecycle import lifecycle
from app.snapshot import build_snapshot
from app.ingest import scan_docs, get_scan_history, init_db
from app.embeddings import embedder
from app.chroma_store import store
from app.ollama_client import generate, generate_stream
import app.connectors.files as file_connector
import app.connectors.gmail as gmail_connector
import app.connectors.calendar as calendar_connector
import app.connectors.contacts as contacts_connector
import app.connectors.notes as notes_connector
import app.connectors.weather as weather_connector
import app.connectors.hue as hue_connector
import app.connectors.news as news_connector
from app.policy_engine import classify
from app.confidence import compute_confidence, interpret, log_feedback
from app.proposal_manager import create_proposal, list_proposals, get_proposal, transition as proposal_transition
from app.execution_engine import execute_proposal, undo_proposal
from app.background_indexer import indexer
from app.web_search import web_search as do_web_search, fetch_url, format_for_llm
from app.voice import transcribe_audio
from app.auth import require_auth, API_TOKEN
from app.rate_limiter import check_chat_limit, check_default_limit
from app.audit import AuditMiddleware
from fastapi import UploadFile, File

DB_PATH = Path(__file__).parent.parent / "data" / "regis.db"


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ollama_pid: int | None = None       # PID of Ollama we started (None = not started by us)
_ollama_started_by_us: bool = False  # Only kill Ollama on shutdown if we spawned it
_server_paused: bool = False  # When True, non-exempt API endpoints return 503


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[type-arg]
    import psutil as _psutil
    init_db()
    _psutil.cpu_percent()   # warm-up: first call always returns 0.0; discard it
    lifecycle.start()       # auto-activate on boot; idempotent
    indexer.start()
    yield
    indexer.stop()
    # Only kill Ollama if this Regis instance started it
    if _ollama_started_by_us and _ollama_pid is not None:
        import os, signal
        try:
            os.kill(_ollama_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


app = FastAPI(title="Regis", version="0.5.0", lifespan=lifespan)


# ── Middleware (SEC-05 audit, SEC-07 security headers + CORS) ─────────────────

class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> HTMLResponse:  # type: ignore[override]
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' https://api.open-meteo.com https://ipapi.co; "
            "script-src 'unsafe-inline'; style-src 'unsafe-inline';"
        )
        return response



class _ApiPauseMiddleware(BaseHTTPMiddleware):
    """Return 503 for all endpoints when API is paused, except health/dashboard/server/* routes.
    Background indexer and suggestion engine run as daemon threads — they are NEVER affected."""
    _EXEMPT = {"/health", "/dashboard", "/server/status", "/server/pause", "/server/resume"}

    async def dispatch(self, request: Request, call_next):
        global _server_paused
        if _server_paused and request.url.path not in self._EXEMPT:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "API paused — background indexing still running. Resume via the dashboard."},
                status_code=503,
            )
        return await call_next(request)

app.add_middleware(_SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8765"])
app.add_middleware(AuditMiddleware)
app.add_middleware(_ApiPauseMiddleware)  # outermost: pause-gate checked first


# ── Core ──────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/snapshot", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def snapshot() -> dict:
    snap = build_snapshot()
    snap["chunks_indexed"] = store.count()
    snap["indexer"] = indexer.get_status()
    return snap


@app.post("/start", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def start() -> dict:
    return lifecycle.start()


@app.post("/pause", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def pause() -> dict:
    return lifecycle.pause()


@app.post("/resume", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def resume() -> dict:
    return lifecycle.resume()


@app.post("/shutdown", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def shutdown() -> dict:
    return lifecycle.shutdown()



# ── Server API Pause / Resume ─────────────────────────────────────────────────
@app.get("/server/status")
def server_api_status() -> dict:
    """Return pause state. No auth required — read by dashboard before token injection."""
    return {"paused": _server_paused, "indexer_running": indexer.get_status().get("running", False)}


@app.post("/server/pause", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def server_api_pause() -> dict:
    """Pause all HTTP API endpoints except /health, /dashboard, /server/*.
    Background indexer and suggestion engine (daemon threads) are NOT affected."""
    global _server_paused
    _server_paused = True
    return {"paused": True, "message": "API paused. Background indexing continues uninterrupted."}


@app.post("/server/resume", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def server_api_resume() -> dict:
    """Resume all HTTP API endpoints from paused state."""
    global _server_paused
    _server_paused = False
    return {"paused": False, "message": "API resumed."}


# ── System Status ─────────────────────────────────────────────────────────────

@app.get("/system/stats", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def system_stats() -> dict:
    """CPU%, RAM%, battery via psutil."""
    import psutil
    batt = psutil.sensors_battery()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "ram_percent": psutil.virtual_memory().percent,
        "battery_percent": round(batt.percent) if batt else None,
        "battery_charging": batt.power_plugged if batt else None,
    }


@app.get("/system/ollama", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def ollama_status() -> dict:
    """Check if Ollama is reachable and return available models."""
    import httpx
    try:
        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"running": True, "models": models}
    except Exception:
        return {"running": False, "models": []}


@app.post("/system/ollama/stop", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def ollama_stop() -> dict:
    """
    Stop the Ollama server. Sends SIGTERM to our tracked PID (if any) + pkill,
    then polls for up to 4s to confirm termination. Falls back to SIGKILL.
    """
    global _ollama_pid, _ollama_started_by_us
    import os, signal, time
    import httpx

    # Ask the macOS Ollama app to quit gracefully first (handles auto-restart case)
    subprocess.run(["osascript", "-e", 'quit app "Ollama"'], capture_output=True)

    # SIGTERM our tracked PID first
    if _ollama_pid is not None:
        try:
            os.kill(_ollama_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        _ollama_pid = None
        _ollama_started_by_us = False

    # pkill covers pre-existing Ollama processes and SIGTERM-resistant cases
    subprocess.run(["pkill", "-x", "ollama"], capture_output=True)
    subprocess.run(["pkill", "-f", "ollama serve"], capture_output=True)

    # Poll up to 4s — return as soon as we can confirm Ollama is gone
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        try:
            httpx.get("http://127.0.0.1:11434/api/tags", timeout=0.5)
            time.sleep(0.5)  # still responding — keep waiting
        except Exception:
            return {"stopped": True}  # confirmed gone

    # Still alive after 4s — escalate to SIGKILL
    subprocess.run(["pkill", "-9", "-x", "ollama"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "ollama serve"], capture_output=True)
    return {"stopped": True}


@app.post("/system/ollama/start", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def ollama_start() -> dict:
    """Start the Ollama server in the background. Guard against double-start."""
    global _ollama_pid, _ollama_started_by_us
    import httpx

    # Already running — don't spawn a second instance
    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=1)
        return {"started": True, "pid": None, "already_running": True}
    except Exception:
        pass

    proc = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _ollama_pid = proc.pid
    _ollama_started_by_us = True
    return {"started": True, "pid": proc.pid}


@app.post("/voice/transcribe", dependencies=[Depends(require_auth), Depends(check_default_limit)])
async def voice_transcribe(audio: UploadFile = File(...)) -> dict:
    """Transcribe an audio file upload using Whisper. Returns {text, language}."""
    data = await audio.read()
    return transcribe_audio(data, filename=audio.filename or "audio.webm")


# ── Intelligence Core ─────────────────────────────────────────────────────────

@app.post("/scan_docs", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def scan_docs_endpoint() -> dict:
    return scan_docs()


@app.get("/search", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def search(q: str = Query(..., min_length=1, max_length=500), k: int = Query(5, ge=1, le=20)) -> dict:
    if store.count() == 0:
        return {"query": q, "results": [], "notice": "No documents indexed yet — run Scan All first."}
    embedding = embedder.embed_one(q)
    results = store.query(embedding, n_results=k)
    return {"query": q, "results": results}


@app.get("/search/web", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def search_web(q: str = Query(..., min_length=1, max_length=500)) -> dict:
    """Web search via DuckDuckGo with zero-trust sanitization."""
    result = do_web_search(q)
    return result


@app.get("/fetch/url", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def fetch_web_url(url: str = Query(...)) -> dict:
    """Fetch and sanitize a specific URL. Content is plain text only."""
    return fetch_url(url)


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=4000)
    use_web: bool = False   # if True, supplement context with a web search


def _source_type(source: str) -> str:
    if source.startswith("file::"): return "file"
    if source.startswith("gmail::"): return "gmail"
    if source.startswith("calendar::"): return "calendar"
    if source.startswith("news::"): return "news"
    return "docs"


_ACTION_KEYWORDS: dict[str, str] = {
    # Email
    "archive": "archive_email",
    "mark as read": "mark_read",
    "move email": "move_email",
    # Calendar
    "create event": "create_calendar_event",
    "add to calendar": "create_calendar_event",
    "schedule meeting": "create_calendar_event",
    # Files — folder keywords must come BEFORE generic "open" patterns
    "move to trash": "delete_file_trash",
    "delete file": "delete_file_trash",
    "open downloads": "open_finder",
    "open desktop": "open_finder",
    "open documents": "open_finder",
    "open movies": "open_finder",
    "open pictures": "open_finder",
    "open music": "open_finder",
    "show my downloads": "open_finder",
    "show my desktop": "open_finder",
    "show my documents": "open_finder",
    "show my movies": "open_finder",
    "show my pictures": "open_finder",
    "show my music": "open_finder",
    "my downloads": "open_finder",
    "my desktop": "open_finder",
    "my documents": "open_finder",
    "my movies": "open_finder",
    "my pictures": "open_finder",
    "my music": "open_finder",
    # OS / UI
    "open finder": "open_finder",
    "show in finder": "open_finder",
    "reveal in finder": "open_finder",
    "open app": "open_app",
    "launch app": "open_app",
    "open website": "open_url",
    "browse to": "open_url",
    "open url": "open_url",
    "go to website": "open_url",
    "search the web": "web_search",
    "search online": "web_search",
    "look it up": "web_search",
    # INFO-01 News
    "open this article": "open_news_article",
    "read this article": "open_news_article",
    "open article": "open_news_article",
    "read the news": "open_news_article",
    "show me the news": "open_news_article",
    # HOME-02 Hue
    "turn on the lights": "hue_turn_on",
    "turn off the lights": "hue_turn_off",
    "lights on": "hue_turn_on",
    "lights off": "hue_turn_off",
    "dim the lights": "hue_set_brightness",
    "dim to": "hue_set_brightness",
    "movie mode": "hue_set_scene",
    "reading mode": "hue_set_scene",
    "set scene": "hue_set_scene",
    "activate scene": "hue_set_scene",
}

# Regex patterns checked when no keyword matches (fallback natural language detection)
_ACTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\b(launch|start)\s+[a-z]', re.I), "open_app"),
    (re.compile(r'\bhttps?://', re.I), "open_url"),
    (re.compile(r'\bopen\s+[a-z]\w{2,}(?:\s+\w+)?\s*$', re.I), "open_app"),
    (re.compile(r'\bsearch\s+(?:the\s+web\s+|online\s+)?(?:for\s+)?', re.I), "web_search"),
    (re.compile(r'\blook\s+up\b', re.I), "web_search"),
]


def _extract_action_params(action_type: str, message: str) -> dict:
    """Best-effort parameter extraction from natural language."""
    msg = message.strip()
    if action_type == "open_app":
        # "launch Photos", "open Spotify", "start Notes", "launch the Photos app"
        m = re.search(
            r'(?:launch|open|start)\s+(?:the\s+)?([A-Za-z][A-Za-z0-9 ]*?)(?:\s+(?:app|for me|please|now))?$',
            msg, re.I,
        )
        if m:
            return {"app_name": m.group(1).strip().title()}
        return {}
    if action_type == "open_url":
        m = re.search(r'(https?://\S+|(?:www\.)\S+)', msg)
        if m:
            url = m.group(1).rstrip('.,;)')
            return {"url": url if url.startswith("http") else "https://" + url}
        return {}
    if action_type == "open_finder":
        common = {
            "downloads": str(Path.home() / "Downloads"),
            "desktop":   str(Path.home() / "Desktop"),
            "documents": str(Path.home() / "Documents"),
            "movies":    str(Path.home() / "Movies"),
            "pictures":  str(Path.home() / "Pictures"),
            "music":     str(Path.home() / "Music"),
        }
        for kw, path in common.items():
            if kw in msg.lower():
                return {"path": path}
        return {}
    if action_type == "web_search":
        query = re.sub(
            r'^(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+(?:it\s+)?up\s*(?:for\s+)?|search\s+online\s+(?:for\s+)?)',
            '', msg, flags=re.I,
        ).strip()
        return {"query": query or msg}
    if action_type == "open_news_article":
        # URL comes from the message or is left empty (user picks from chat context)
        m = re.search(r'(https?://\S+)', msg)
        if m:
            return {"url": m.group(1).rstrip('.,;)')}
        return {}
    if action_type in ("hue_turn_on", "hue_turn_off"):
        return {"light_id": "1"}   # default; LLM context can refine via ChromaDB
    if action_type == "hue_set_brightness":
        m = re.search(r'(\d+)\s*%', msg)
        if m:
            pct = int(m.group(1))
            return {"light_id": "1", "brightness": int(pct * 254 / 100)}
        return {"light_id": "1", "brightness": 127}
    if action_type == "hue_set_scene":
        return {"scene_id": ""}   # filled by LLM from indexed Hue scenes in ChromaDB
    return {}


_GREETING_RE = re.compile(
    r'^(hey|hi+|hello+|yo+|sup|howdy|greetings?|what\'?s\s+up|'
    r'how\s+are\s+you|how\s+do\s+you\s+do|'
    r'good\s+(morning|afternoon|evening|night))[.!?,\s]*$',
    re.I,
)


def _build_prompt(message: str, chunks: list, web_context: str | None = None) -> str:
    # Casual greeting — skip context injection, respond naturally
    if _GREETING_RE.match(message.strip()) and not web_context:
        return (
            "You are Regis, a friendly personal AI assistant running locally on macOS. "
            "Respond naturally and briefly to the user's greeting. "
            "You can mention you're ready to help with files, emails, schedule, or anything else.\n\n"
            f"User: {message}\n\nRegis:"
        )
    local_context = "\n\n---\n\n".join(
        f"[{_source_type(c['source'])}: {c['source']}]\n{c['document']}" for c in chunks
    )
    web_section = f"\n\nWeb Context:\n{web_context}" if web_context else ""
    no_index_note = (
        "\n\n[Note: No local files have been indexed yet. "
        "Suggest the user click 'Scan All' to index their files.]"
        if not chunks else ""
    )
    return (
        "You are Regis, a personal AI assistant running locally on macOS. "
        "You have access to the user's files, emails, and schedule (when indexed). "
        "Answer using the context below. If the answer isn't there, say so and offer to search the web.\n\n"
        f"Local Context:\n{local_context or '(nothing indexed yet)'}"
        f"{web_section}{no_index_note}\n\n"
        f"Question: {message}\n\nAnswer:"
    )


def _proposal_hint(message: str) -> dict | None:
    msg_lower = message.lower()
    best_action: str | None = None
    best_score: float = 0.0
    best_intent: str = ""

    # Score every matching keyword by phrase length (longer = more specific).
    # weight = min(word_count / 3.0, 1.0) — a 3-word phrase scores 1.0.
    for keyword, kw_action in _ACTION_KEYWORDS.items():
        if keyword in msg_lower:
            weight = min(len(keyword.split()) / 3.0, 1.0)
            if weight > best_score:
                best_score  = weight
                best_action = kw_action
                best_intent = keyword

    # Regex fallback — fixed score of 0.55 (below any 2-word keyword match)
    if best_action is None:
        for pattern, pat_action in _ACTION_PATTERNS:
            if pattern.search(message):
                best_action = pat_action
                best_intent = pat_action
                best_score  = 0.55
                break

    if best_action is None:
        return None

    params = _extract_action_params(best_action, message)
    decision = classify(best_action)
    # Pass detection_score into context → +0.05 activity boost for clear intent
    confidence = compute_confidence(best_action, params, context={"detection_score": best_score})
    return {
        "detected_intent":           best_intent,
        "suggested_action":          best_action,
        "params":                    params,
        "risk_tier":                 decision.tier.value,
        "confidence":                confidence,
        "confidence_interpretation": interpret(confidence),
        "detection_score":           round(best_score, 3),
    }


def _save_message(role: str, content: str) -> None:
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO chat_messages (id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), role, content, _now()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _sse_stream(
    prompt: str,
    sources: list,
    hint: dict | None,
    user_msg: str,
    action_executed: dict | None = None,
) -> Generator[str, None, None]:
    meta: dict = {"sources": sources}
    if hint:
        meta["proposal_hint"] = hint
    if action_executed:
        meta["action_executed"] = action_executed
    yield f"data: {json.dumps(meta)}\n\n"

    full_response = ""
    for token in generate_stream(prompt):
        full_response += token
        yield f"data: {json.dumps({'token': token})}\n\n"
    yield "data: [DONE]\n\n"

    # Persist both sides of the conversation
    _save_message("user", user_msg)
    _save_message("assistant", full_response)


@app.post("/chat", response_model=None, dependencies=[Depends(require_auth), Depends(check_chat_limit)])
def chat(req: ChatRequest, stream: bool = Query(False)) -> dict | StreamingResponse:
    """
    Answer using retrieved context. ?stream=true returns SSE.
    use_web=true in body supplements with a DuckDuckGo search.
    Works even if nothing is indexed (returns helpful guidance).
    """
    chunks: list = []
    if store.count() > 0:
        embedding = embedder.embed_one(req.message)
        chunks = store.query(embedding, n_results=12)

    sources = [
        {"source": c["source"], "source_type": _source_type(c["source"]), "score": c["score"]}
        for c in chunks
    ]

    web_context: str | None = None
    if req.use_web:
        web_result = do_web_search(req.message)
        web_context = format_for_llm(web_result)

    prompt = _build_prompt(req.message, chunks, web_context)
    hint = _proposal_hint(req.message)

    # Auto-execute LOW-risk actions with extractable params
    action_executed: dict | None = None
    if hint and hint.get("risk_tier") == "LOW" and hint.get("params"):
        try:
            prop = create_proposal(
                hint["suggested_action"],
                hint["params"],
                "LOW",
                hint["confidence"],
            )
            proposal_transition(prop["id"], "APPROVED")
            log_feedback(hint["suggested_action"], approved=True)
            exec_result = execute_proposal(prop["id"])
            action_executed = {
                "action": hint["suggested_action"],
                "result": exec_result.get("result", {}),
            }
        except Exception as exc:
            action_executed = {"action": hint["suggested_action"], "error": str(exc)}

    if stream:
        return StreamingResponse(
            _sse_stream(prompt, sources, hint, req.message, action_executed),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    answer = generate(prompt)
    _save_message("user", req.message)
    _save_message("assistant", answer)

    response: dict = {"answer": answer, "sources": sources}
    if hint:
        response["proposal_hint"] = hint
    if action_executed:
        response["action_executed"] = action_executed
    return response


@app.get("/chat/history", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def chat_history(limit: int = Query(60, ge=1, le=200)) -> dict:
    """Return the most recent chat messages (newest last for chronological display)."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT role, content, created_at FROM chat_messages ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return {"messages": [dict(r) for r in reversed(rows)]}
    except Exception:
        return {"messages": []}


@app.delete("/chat/history", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def clear_chat_history() -> dict:
    """Clear all chat history."""
    conn = _get_db()
    conn.execute("DELETE FROM chat_messages")
    conn.commit()
    conn.close()
    return {"cleared": True}


@app.get("/scan_history", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def scan_history() -> dict:
    return {"history": get_scan_history()}


# ── Connectors ────────────────────────────────────────────────────────────────

_CONNECTORS = {
    "files": file_connector,
    "gmail": gmail_connector,
    "calendar": calendar_connector,
    "contacts": contacts_connector,
    "notes": notes_connector,
    "weather": weather_connector,
    "hue": hue_connector,
    "news": news_connector,
}


@app.post("/connectors/{name}/scan", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def connector_scan(name: str) -> dict:
    """Trigger a connector scan. name: files | gmail | calendar | all"""
    if name == "all":
        results: dict = {}
        for conn_name, conn_mod in _CONNECTORS.items():
            try:
                results[conn_name] = conn_mod.scan()
            except Exception as exc:
                results[conn_name] = {"connector": conn_name, "status": "ERROR", "message": str(exc)}
        # Also scan docs
        try:
            results["docs"] = scan_docs()
        except Exception as exc:
            results["docs"] = {"status": "ERROR", "message": str(exc)}
        return {"results": results}

    if name not in _CONNECTORS:
        raise HTTPException(status_code=404, detail=f"Unknown connector '{name}'. Valid: files, gmail, calendar, all")

    try:
        return _CONNECTORS[name].scan()
    except Exception as exc:
        return {"connector": name, "status": "ERROR", "message": str(exc)}


@app.post("/connectors/force_index", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def force_index() -> dict:
    """Trigger a full index immediately, bypassing idle/charging gates. For manual re-index."""
    results: dict = {}
    try:
        results["docs"] = scan_docs()
    except Exception as exc:
        results["docs"] = {"status": "ERROR", "message": str(exc)}
    for name, mod in _CONNECTORS.items():
        try:
            results[name] = mod.scan()
        except Exception as exc:
            results[name] = {"status": "ERROR", "message": str(exc)}
    total_chunks = store.count()
    return {"results": results, "total_chunks": total_chunks}


# ── HOME-01: Weather ─────────────────────────────────────────────────────────

@app.get("/weather", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def weather_endpoint() -> dict:
    """Return current conditions + 7-day forecast from OpenWeather (30-min cache)."""
    from app.connectors.weather import fetch_weather
    return fetch_weather()


# ── INFO-01: News endpoint ───────────────────────────────────────────────────

@app.get("/news", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def news_endpoint() -> dict:
    """Return current top headlines from NewsAPI (2-hour cache)."""
    from app.connectors.news import fetch_headlines
    return fetch_headlines()


# ── HOME-02: Hue read endpoints ───────────────────────────────────────────────

@app.get("/hue/lights", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def hue_lights() -> dict:
    """List all Hue lights from the bridge."""
    from app.connectors.hue import get_lights
    return get_lights()


@app.get("/hue/scenes", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def hue_scenes() -> dict:
    """List all Hue scenes from the bridge."""
    from app.connectors.hue import get_scenes
    return get_scenes()


# ── Policy & Execution ────────────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    action_type: str = Field(..., max_length=100)
    parameters: dict = {}
    context: dict = {}

    @field_validator("parameters")
    @classmethod
    def _check_parameters(cls, v: dict) -> dict:
        if len(v) > 15:
            raise ValueError("parameters map must have ≤ 15 keys")
        return v


@app.post("/propose", dependencies=[Depends(require_auth), Depends(check_chat_limit)])
def propose(req: ProposeRequest) -> dict:
    decision = classify(req.action_type)
    confidence = compute_confidence(req.action_type, req.parameters, req.context)

    proposal = create_proposal(
        action_type=req.action_type,
        parameters=req.parameters,
        risk_tier=decision.tier.value,
        confidence=confidence,
        rejection_reason=None if decision.allowed else decision.reason,
    )

    # LOW + confidence ≥ 0.30 → auto-execute
    if decision.tier.value == "LOW" and confidence >= 0.30 and proposal["status"] == "PROPOSED":
        try:
            proposal_transition(proposal["id"], "APPROVED")
            log_feedback(req.action_type, approved=True)
            result = execute_proposal(proposal["id"])
            proposal = get_proposal(proposal["id"])
            return {
                "proposal": proposal,
                "auto_executed": True,
                "execution_result": result,
                "confidence_interpretation": interpret(confidence),
            }
        except Exception as exc:
            proposal = get_proposal(proposal["id"])
            return {
                "proposal": proposal,
                "auto_executed": False,
                "error": str(exc),
                "confidence_interpretation": interpret(confidence),
            }

    return {
        "proposal": proposal,
        "auto_executed": False,
        "confidence_interpretation": interpret(confidence),
        "policy_reason": decision.reason,
    }


@app.get("/proposals", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def proposals_list(status: str | None = None) -> dict:
    return {"proposals": list_proposals(status=status)}


class TransitionRequest(BaseModel):
    new_status: str
    reason: str | None = None


@app.post("/transition/{proposal_id}", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def transition_proposal(proposal_id: str, req: TransitionRequest) -> dict:
    if req.new_status == "UNDO":
        result = undo_proposal(proposal_id)
        return {"undone": True, "result": result}

    updated = proposal_transition(proposal_id, req.new_status, reason=req.reason)

    # Log feedback for confidence learning
    if req.new_status == "APPROVED":
        p = get_proposal(proposal_id)
        if p:
            log_feedback(p["action_type"], approved=True)
        try:
            result = execute_proposal(proposal_id)
            updated = get_proposal(proposal_id)
            return {"proposal": updated, "execution_result": result}
        except Exception as exc:
            updated = get_proposal(proposal_id)
            return {"proposal": updated, "execution_error": str(exc)}

    if req.new_status == "REJECTED":
        p = get_proposal(proposal_id)
        if p:
            log_feedback(p["action_type"], approved=False)

    return {"proposal": updated}


# ── Proactive Indexing ────────────────────────────────────────────────────────

@app.get("/indexer/status", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def indexer_status() -> dict:
    return indexer.get_status()


# ── Suggestions ───────────────────────────────────────────────────────────────

def _fmt_event_date(iso: str) -> str:
    """Format a calendar start date for display. Returns 'Today', 'Tomorrow', 'Mon Apr 6', etc."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        today = datetime.now(timezone.utc).date()
        event_date = d.date()
        delta = (event_date - today).days
        if delta == 0:
            time_part = d.strftime("%-I:%M %p") if d.hour or d.minute else ""
            return f"Today{' ' + time_part if time_part else ''}"
        if delta == 1:
            time_part = d.strftime("%-I:%M %p") if d.hour or d.minute else ""
            return f"Tomorrow{' ' + time_part if time_part else ''}"
        return d.strftime("%a %b %-d")
    except Exception:
        return iso[:10]


@app.get("/suggestions", dependencies=[Depends(require_auth), Depends(check_default_limit)])
def suggestions() -> dict:
    if store.count() == 0:
        return {"suggestions": [
            {"type": "setup", "title": "Index your files", "subtitle": "Nothing indexed yet",
             "text": "Scan all my files and documents", "source": None},
            {"type": "setup", "title": "What can Regis do?", "subtitle": "Getting started",
             "text": "What can you do?", "source": None},
        ]}

    results: list[dict] = []
    seen: set[str] = set()
    today_str = datetime.now(timezone.utc).date().isoformat()

    # ── Screenshots on Desktop (macOS naming convention) ──────────────────────
    # macOS names screenshots "Screenshot YYYY-MM-DD at HH.MM.SS AM.png" — no age logic,
    # purely pattern-based. Most recent first.
    try:
        desktop = Path.home() / "Desktop"
        screenshots = sorted(
            desktop.glob("Screenshot*.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:2]
        for shot in screenshots:
            src = str(shot)
            if src not in seen:
                seen.add(src)
                results.append({
                    "type": "screenshot",
                    "title": shot.name,
                    "subtitle": "Desktop screenshot",
                    "text": f"What's in this screenshot: {shot.name}?",
                    "source": src,
                })
    except Exception:
        pass

    # ── LLM-cached suggestions (generated during night-window idle) ──────────
    # These are richer and context-aware. Use if cache is fresh; fall back to
    # inline ChromaDB queries if cache is cold (first run / daytime).
    try:
        from app.suggestion_engine import get_cached
        cached = get_cached()
        for s in cached[:4]:
            key = s.get("text", "")
            if key not in seen:
                seen.add(key)
                results.append(s)
    except Exception:
        pass

    # ── Inline fallback: calendar, email, files (runs when cache cold) ────────
    if len(results) < 3:
        # Calendar: upcoming events, closest first
        try:
            cal_chunks = store.get_where({"source_type": {"$eq": "calendar"}}, limit=200)
            cal_upcoming = sorted(
                [c for c in cal_chunks if c.get("start", "") >= today_str],
                key=lambda c: c.get("start", ""),
            )
            for c in cal_upcoming[:2]:
                src = c.get("source", "")
                if src in seen:
                    continue
                seen.add(src)
                title = c.get("title", "Event")
                results.append({
                    "type": "meeting",
                    "title": title,
                    "subtitle": _fmt_event_date(c.get("start", "")),
                    "text": f"Tell me about: {title}",
                    "source": src,
                })
        except Exception:
            pass

        # Email: recent relevant
        try:
            email_hits = store.query(
                embedder.embed_one("urgent email reply inbox unread message"),
                n_results=8,
                where={"source_type": {"$eq": "gmail"}},
            )
            for hit in email_hits[:2]:
                src = hit.get("source", "")
                if src in seen:
                    continue
                seen.add(src)
                subject = hit.get("subject", "Email")
                sender = hit.get("sender", "")
                sender_name = sender.split("<")[0].strip() or sender.split("@")[0]
                results.append({
                    "type": "email",
                    "title": subject,
                    "subtitle": f"From {sender_name}" if sender_name else "",
                    "text": f"Summarize this email: {subject}",
                    "source": src,
                })
        except Exception:
            pass

        # Files: relevant local files
        try:
            file_hits = store.query(
                embedder.embed_one("recent document notes summary important"),
                n_results=8,
                where={"source_type": {"$eq": "file"}},
            )
            for hit in file_hits[:2]:
                src = hit.get("source", "")
                if src in seen:
                    continue
                seen.add(src)
                path = src[len("file::"):] if src.startswith("file::") else src
                name = path.split("/")[-1] or path
                results.append({
                    "type": "file",
                    "title": name,
                    "subtitle": path.replace(str(Path.home()), "~"),
                    "text": f"What's in {name}?",
                    "source": path,
                })
        except Exception:
            pass

    return {"suggestions": results[:6]}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    html_path = Path(__file__).parent / "dashboard.html"
    html = html_path.read_text()
    html = html.replace("__REGIS_TOKEN__", API_TOKEN)
    return HTMLResponse(content=html)
