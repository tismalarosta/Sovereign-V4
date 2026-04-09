# CLAUDE.md — Sovereign V3

This is the Claude Code configuration file. It points to the real governance document.

**Read AGENTS.md first. Always. Every session.**

Then read:
1. `docs/PHASE_STATUS.md` — current phase and what's allowed
2. `docs/INVARIANTS.md` — rules you must never break
3. `docs/AGENT_MISTAKES.md` — mistakes to avoid repeating

## Quick Reference

- Python: `./venv/bin/python` (never system Python)
- Run: `uvicorn app.main:app --host 127.0.0.1 --port 8765` (no --reload)
- LLM: Ollama + Mistral (local) — no paid APIs
- DB: SQLite at `data/regis.db` + ChromaDB at `data/chroma/`
- Current phase: **see docs/PHASE_STATUS.md**

## Non-Negotiables

1. No feature from a higher phase without updating PHASE_STATUS.md first
2. One authority per domain — see AGENTS.md
3. Deny by default — unknown actions = ULTRA risk (hard deny)
4. Stability > features — broken boot = rollback immediately
5. Every task updates CHANGELOG.md and CURRENT_STATE.md

See AGENTS.md for full details.
