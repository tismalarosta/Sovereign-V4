# AGENT_MISTAKES.md — Institutional Memory

This file is the error log for architectural drift. Any AI agent that violates INVARIANTS.md, leaks into a higher phase, adds premature complexity, or breaks boot stability must log it here.

Agents must review this file before starting any task.

---

## Entry Format

```
Date: YYYY-MM-DD
Mistake: What was done wrong
Violation: Which invariant or rule was broken
Correction: What was done to fix it
Prevention Rule: How to detect and stop this next time
```

---

## Log

### V1 Era Mistakes (Inherited Knowledge)

**Date:** Pre-V3
**Mistake:** Multiple control surfaces (CLI, dashboard, scripts) all mutating system state simultaneously
**Violation:** One Authority Per Domain
**Correction:** Enforced single lifecycle authority in V2
**Prevention Rule:** Before adding any new interface or control surface, ask: "Is there already a component that owns this domain?" If yes, route through it.

---

**Date:** Pre-V3
**Mistake:** Dashboard tried to "fix" backend problems by computing state client-side
**Violation:** Snapshot Is Law
**Correction:** UI reads ONLY from /snapshot endpoint
**Prevention Rule:** UI components must never compute or cache system state independently. All state from /snapshot, always.

---

**Date:** Pre-V3
**Mistake:** Too many daemons and background workers launched before core was stable
**Violation:** Phase Lock, Complexity Budget
**Correction:** Phase 1-2 hard limit: no daemons, no background workers
**Prevention Rule:** If you're thinking about a daemon, ask: "Is the core stable yet?" If no, defer. If yes, check PHASE_STATUS.md.

---

**Date:** Pre-V3
**Mistake:** Used Python 3.14 — caused pkg_resources / google-api-python-client incompatibilities
**Violation:** Environment Rules (stability invariant)
**Correction:** Pin to Python 3.12
**Prevention Rule:** Python version is part of the dependency graph. Never use bleeding-edge Python for a project with Google API dependencies. Stick to 3.12.

---

**Date:** Pre-V3
**Mistake:** Agent created new random markdown files instead of updating canonical docs
**Violation:** No Docs Sprawl
**Correction:** Strict canonical file list enforced in AGENTS.md
**Prevention Rule:** Before creating any .md file, check if it's in the canonical list. If not, it cannot be created. Updates go into existing canonical files.

---

**Date:** Pre-V3
**Mistake:** Added too many abstraction layers (policy, proposals, suppression, autonomy) before core was stable
**Violation:** Phase Lock, Stability > Features
**Correction:** Phase-locked development with explicit unlock criteria
**Prevention Rule:** "Does the health endpoint return 200 consistently?" If not, no new features. No exceptions.

---

---

**Date:** 2026-04-03
**Mistake:** ChromaDB `where` filter used `$gte` on a string field (`start`): `{"start": {"$gte": today_str}}`. This silently throws an exception caught by the outer try/except, returning 0 suggestions.
**Violation:** Stability > Features (silent failure, wrong behavior)
**Correction:** Fetched all docs with `$eq` source_type filter, then filtered by date in Python.
**Prevention Rule:** ChromaDB only supports `$gte`/`$lte`/`$gt`/`$lt` on **numeric** metadata fields. For string date filtering, always do Python-side filtering after fetch.

---

**Date:** 2026-04-03
**Mistake:** `openChip()` and `openSuggSource()` passed the raw source key (`file::/abs/path`) directly to `open_finder`. The `file::` prefix is not a valid filesystem path — `Path("file::/abs/path")` does not resolve correctly.
**Violation:** Correctness (Finder reveal silently fails)
**Correction:** Strip `file::` prefix before passing to `open_finder`: `source.replace(/^file::/, '')`.
**Prevention Rule:** The `source` field in ChromaDB metadata for file type is `"file::<abs_path>"` — always strip the prefix before using it as a filesystem path.

---

**Date:** 2026-04-03
**Mistake:** `ingest.py` stores doc source as `md_file.name` (just filename, e.g. `CHANGELOG.md`), not a full path. Attempting `open_finder` on a bare filename resolves against CWD, and the docs directory is inside the blocked project root anyway — so Finder reveal always fails for docs chips.
**Violation:** Correctness (Finder open silently denied)
**Correction:** Docs chips now trigger a chat query ("What does CHANGELOG.md say?") instead of Finder open.
**Prevention Rule:** Before calling `open_finder`, verify the source has an absolute path to a location inside `Path.home()`. Docs (`source_type` absent / `docs`) are stored by filename only — never pass them to `open_finder`.

---

*Future mistakes go here, newest at the bottom.*
---

**Date:** 2026-04-08
**Mistake:** Used `pkill -f run.py` to restart the server, but the launchd-managed process runs as `uvicorn app.main:app` — not run.py. The kill had zero effect. The stale process (started Thu Apr 2) kept serving on port 8765 for 5+ days without anyone noticing.
**Violation:** Ops correctness
**Correction:** `launchctl unload ~/Library/LaunchAgents/com.regis.sovereign.plist` then `launchctl load` to properly cycle the managed process.
**Prevention Rule:** When launchd manages the server, NEVER use pkill/kill. Always use `launchctl unload/load`. Confirm with `launchctl list | grep regis` before and after. The correct PID owner is launchd, not a shell.

---

**Date:** 2026-04-08
**Mistake:** Dashboard showing "Chunks=0, Last scan=Never run yet" was accepted as accurate system state when it was actually a complete lie caused by auth failure. ChromaDB had 9,624 items the whole time.
**Violation:** Snapshot Is Law — all state must be read from /snapshot, not inferred from the dashboard UI
**Correction:** Always verify raw snapshot directly: `curl http://127.0.0.1:8765/snapshot -H "Authorization: Bearer $(cat data/.api_token)"`. UI showing zeros means the UI is broken, not necessarily that data is missing.
**Prevention Rule:** Before declaring indexing broken, check the snapshot endpoint directly. Dashboard display = unreliable derivative. ChromaDB item count = ground truth.

---

**Date:** 2026-04-08
**Mistake:** Gmail connector showing `status=NOT_CONFIGURED, items_indexed=0` in the connectors table was misread as "Gmail credentials not working." In reality, 1,236 gmail items existed in ChromaDB and the token was valid.
**Violation:** Accuracy — connectors table records last scan result, not current data state
**Correction:** Checked ChromaDB item counts by source_type independently. Found gmail:1236. Ran `_get_credentials()` manually — returned valid Credentials object.
**Prevention Rule:** `connectors.status` = result of the last scan run, not current connectivity. Always cross-check against ChromaDB counts. A NOT_CONFIGURED scan result does not mean data is absent.
