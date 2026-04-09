# AGENTS.md — Sovereign V3 AI Governance Document

## READ THIS FIRST

This file is the constitution for any AI agent (Claude Code, PyCharm Copilot, or any other) working on this project. You must read and comply with it before touching any code.

If you are Claude Code: this file is your CLAUDE.md equivalent. Follow it completely.
If you are a PyCharm AI assistant: read this before writing any code or suggesting any changes.
If you are any other agent: same rules apply.

---

## What This Project Is

**Sovereign V3** is a local-first, sovereign AI assistant system for macOS M2.
**Owner:** Matisse Lurie-Giner
**Assistant name:** Regis
**Root path:** `~/Sovereign V3/`

The goal: a personal AI agent that indexes your files, emails, and calendar locally — proposes and executes actions through strict policy gating — runs entirely offline — costs nothing to operate — and never crashes.

---

## Current Phase

**Check `docs/PHASE_STATUS.md` for the current phase before doing anything.**

You must know the current phase before implementing anything. Features from higher phases are FORBIDDEN until that phase is unlocked.

---

## The Four Rules You Must Never Break

### 1. PHASE LOCK
No feature from a higher phase may be implemented without first updating `docs/PHASE_STATUS.md`. If you are tempted to add something "just quickly" that belongs to a later phase — stop. Log it as deferred in `docs/PROJECT_PLAN.md` and move on.

### 2. ONE AUTHORITY PER DOMAIN
- Lifecycle state → only `app/lifecycle.py`
- Policy decisions → only `app/policy_engine.py`
- Execution → only `app/execution_engine.py`
- System state → only `app/snapshot.py` (the `/snapshot` endpoint)
- UI never guesses state — it reads ONLY from `/snapshot`

### 3. DENY BY DEFAULT
Every action that is not explicitly allowed is denied. Unknown tools default to ULTRA risk (hard deny). The policy engine is the gatekeeper — nothing bypasses it.

### 4. STABILITY > FEATURES
If boot is broken, rollback immediately. No new features until boot is stable. No exceptions.

---

## Complexity Budget

Phase 1–2 hard limits (you must stay within these):
- 1 Python process
- 1 SQLite database (`data/regis.db`)
- 1 vector store (`data/chroma/`)
- Max 12 API endpoints
- No daemon threads beyond minimal required for web server
- No background schedulers
- No inter-process communication

Phase 5 baseline: **26 endpoints** (as of Phase 5.3 + Phase 6 Session 1).
Phase 6 cap: **32 endpoints**.
Phase 10 actual: **~38 endpoints** (weather, hue/lights, hue/scenes added). New cap: **45 endpoints** through Phase 12.
Phase 13+ requires updating this file with a new cap before adding endpoints.

---

## Tech Stack (Follow Exactly)

| Component | Technology | Notes |
|-----------|------------|-------|
| Python | 3.12 (from `venv/`) | Never use system Python or 3.14 |
| API server | FastAPI + Uvicorn | localhost only, single process |
| LLM | Ollama + Gemma 4 E4B (configured; pull after Ollama update) | Local, free — no Claude API, no OpenAI |
| Embeddings | sentence-transformers (MiniLM-L6-v2) | Local, free |
| Vector DB | ChromaDB | Local, embedded |
| Database | SQLite at `data/regis.db` | Single database, no exceptions |
| Package env | venv at `venv/` | Always `source venv/bin/activate` |

**Never:**
- Use `python3` or system Python — always `./venv/bin/python`
- Use `uvicorn --reload` — spawns subprocesses, breaks single-process constraint
- Use paid APIs (Claude API, OpenAI API) — this project is zero-cost
- Add a dependency without updating `requirements.txt`

---

## Document Rules

**Only these docs folders/files are canonical:**
- `docs/INDEX.md`, `docs/VISION.md`, `docs/INVARIANTS.md`
- `docs/PHASE_STATUS.md`, `docs/PROJECT_PLAN.md`, `docs/CHANGELOG.md`
- `docs/RISK_MODEL.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_MISTAKES.md`
- `docs/CURRENT_STATE.md` — updated after every completed task
- `docs/SETUP_GUIDE.md` — API key and service setup instructions for the user

**Never create new markdown files outside `docs/`. Per-task update files only at:**
`docs/task_updates/YYYY-MM-DD_taskname.md`

**Every task must:**
1. Append to `docs/CHANGELOG.md`
2. Update `docs/CURRENT_STATE.md`
3. Update `docs/PHASE_STATUS.md` if phase changed
4. Log any mistakes in `docs/AGENT_MISTAKES.md` (format: Date / Mistake / Violation / Correction / Prevention Rule)

---

## Before Every Task

1. Read `AGENTS.md` (this file)
2. Read `docs/PHASE_STATUS.md` — confirm current phase
3. Read `docs/INVARIANTS.md` — confirm nothing you're about to do violates invariants
4. Read `docs/AGENT_MISTAKES.md` — check if your proposed change has been flagged before

---

## Risk Tiers (Summary)

| Tier | Behavior | Examples |
|------|----------|---------|
| LOW | Auto-execute (confidence ≥ 0.30) | Archive old emails, index files, metadata updates |
| MEDIUM | Approve → Execute (confidence ≥ 0.70) | Move email, create calendar event, delete to trash |
| HIGH | Draft only — human finalizes | Payments, legal emails, permanent deletion |
| ULTRA | Hard deny — always | Keychain, database drop, policy engine modification, self-escalation |

---

## The Confidence System

Every proposed action has a confidence score (0.0–1.0):
- < 0.30: Ask clarifying question, do not propose
- 0.30–0.70: Can trigger LOW auto-execute only
- ≥ 0.70: Required for MEDIUM approval path
- HIGH and ULTRA are blocked regardless of confidence

---

## Running the App

```bash
# Activate venv (always)
source venv/bin/activate

# Start server (single process, no --reload)
uvicorn app.main:app --host 127.0.0.1 --port 8765

# Check it works
curl http://localhost:8765/health
curl http://localhost:8765/snapshot
```

---

## Collaboration Model

This project uses two AI coding assistants alongside the owner:

**Claude (via Cowork)** — Strategic planning, documentation, architecture decisions, major reviews. Acts as the architect. Changes to AGENTS.md, INVARIANTS.md, or PHASE_STATUS.md must go through Claude first.

**Claude Code (terminal)** — Implementation. Reads AGENTS.md automatically. Must never violate phase constraints or invariants.

**PyCharm Copilot** — Local coding assistance. Must be reminded to read AGENTS.md at the start of every session. Should never add features or dependencies not listed in PROJECT_PLAN.md.

**Rule:** If Claude Code or PyCharm Copilot and this document disagree, this document wins. Always.
