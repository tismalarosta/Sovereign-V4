# RISK_MODEL.md — Action Risk Tiers for Sovereign V3

Every action Regis proposes must be classified into one of four risk tiers. This classification happens in the policy engine — not in the LLM.

---

## 🟢 LOW — Auto-Execute

**Definition:** Reversible, local, non-destructive. No financial impact, no outbound communication, no external mutations.

**Execution:** May execute without user approval. Requires confidence ≥ 0.30. Must be journaled.

**Examples:**
- Archive promotional emails older than 30 days
- Mark newsletters as read
- Add internal metadata tags to files
- Rebuild vector index
- Clean temporary runtime files
- Re-run failed indexing job

---

## 🟡 MEDIUM — Approve → Execute

**Definition:** Modifies real systems but remains reversible. No financial impact.

**Execution:** Requires explicit user approval before execution. Must show preview. Must log in action_log. Must support undo. Requires confidence ≥ 0.70.

**Examples:**
- Move email to a folder
- Remove a label
- Create a calendar event
- Update a calendar event
- Delete a file to Trash (not permanently)
- Draft and send a reply (after explicit send approval)

---

## 🔴 HIGH — Draft Only, Human Finalizes

**Definition:** Irreversible, financial, reputational, or security-impacting. Regis may prepare but never execute.

**Execution:** Regis prepares drafts, summaries, or checklists. Human performs the final action. No override path.

**Examples:**
- Transfer money / payment
- Submit a tax form
- Send a legally sensitive email
- Permanently delete files (bypass Trash)
- Change system security settings

---

## ⚫ ULTRA — Hard Deny

**Definition:** Core system authority, secrets, or irreversible destruction. Never permitted under any circumstances.

**Execution:** Always refused. No escalation path. No override.

**Examples:**
- Access macOS Keychain raw entries
- Exfiltrate private keys or credentials
- Modify /etc or system-level files
- Drop database tables or delete ChromaDB
- Modify the policy engine itself
- Grant higher autonomy to itself
- Self-modification of any governance document

---

## Confidence Thresholds

| Score | Behavior |
|-------|----------|
| < 0.30 | Ask clarifying question — do not propose action |
| 0.30–0.69 | Can trigger LOW auto-execute only |
| ≥ 0.70 | Required for MEDIUM approval path |
| Any score | HIGH = draft only, ULTRA = hard deny always |

---

## Global Rules

- All actions must pass risk classification before execution
- Risk classification is performed by `app/policy_engine.py` — never by the LLM
- Risk tier expansion across phases requires PHASE_STATUS.md update
- ULTRA tier is immutable — no override, no exceptions
- All actions journaled in SQLite before execution begins
