# INVARIANTS.md — Non-Negotiable Rules for Sovereign V3

These rules cannot be overridden by any agent, any phase, or any deadline pressure.

---

## 1. Phase Lock
- No feature from a higher phase without updating PHASE_STATUS.md first
- Phase escalation requires explicit unlock criteria to be met and documented
- Complexity budget must stay within phase limits

## 2. Single Authority Per Domain
- Lifecycle state: only `app/lifecycle.py`
- Policy decisions: only `app/policy_engine.py`
- Execution: only `app/execution_engine.py`
- System state for UI: only `/snapshot` endpoint from `app/snapshot.py`
- No other component may compute or store authoritative versions of these

## 3. Snapshot Is Law
- UI reads ONLY from `/snapshot`
- Snapshot must never lie: no NaN, Infinity, or fake values
- Null means unknown — never invent a value
- Emergency stop must return immediately (non-blocking)

## 4. Deny By Default
- Nothing executes unless explicitly allowed by the policy engine
- Unknown tools = ULTRA risk (hard deny)
- No bypassing the policy engine under any circumstances

## 5. Stability Invariants
- Boot must always succeed — if boot breaks, rollback immediately
- No recovery system before baseline stability
- No background mutation during Phase 1–2
- Stability > features. Always.

## 6. No Side Channels
- All mutations: user intent → policy engine → executor → DB
- No UI-to-executor shortcuts
- No LLM-to-executor shortcuts (LLM proposes, policy gates, user approves, executor acts)

## 7. Complexity Budget (Phase 1–2)
- 1 Python process
- 1 SQLite database
- 1 vector store (ChromaDB)
- Max 12 API endpoints
- No daemon threads beyond minimal web server requirements
- No background schedulers
- No inter-process communication

## 8. No Invisible Behavior
- Everything must be visible, stoppable, and inspectable
- All actions journaled in SQLite before execution
- All state changes logged

## 9. No Docs Sprawl
- Only canonical docs in `docs/`
- No random markdown files created by agents
- Every task updates CHANGELOG.md and CURRENT_STATE.md

## 10. Environment Rules
- Always use `./venv/bin/python` (Python 3.12)
- Never use system Python, python3, or Python 3.14
- Never use `uvicorn --reload`
- Never add a dependency without updating `requirements.txt`

## 11. Governance Hierarchy
- AGENTS.md > any agent's own judgment
- INVARIANTS.md > PHASE_STATUS.md > PROJECT_PLAN.md
- If a simpler solution exists, choose it
- If a daemon seems necessary in Phase 1–2, it is not

## 12. Enforcement
Any agent must:
1. Read AGENTS.md before making changes
2. Confirm current phase from PHASE_STATUS.md
3. Refuse to implement anything that violates these invariants
4. Log violations in AGENT_MISTAKES.md
