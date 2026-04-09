"""
20+ test cases for app/policy_engine.py

Run with: ./venv/bin/python -m pytest tests/test_policy_engine.py -v
"""

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))

from app.policy_engine import classify, RiskTier, PolicyDecision


# ── LOW tier ──────────────────────────────────────────────────────────────────

def test_archive_email_is_low():
    d = classify("archive_email")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

def test_mark_read_is_low():
    d = classify("mark_read")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

def test_add_metadata_tag_is_low():
    d = classify("add_metadata_tag")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

def test_rebuild_index_is_low():
    d = classify("rebuild_index")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

def test_clean_temp_files_is_low():
    d = classify("clean_temp_files")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

def test_rerun_index_is_low():
    d = classify("rerun_index")
    assert d.tier == RiskTier.LOW
    assert d.allowed is True

# ── MEDIUM tier ───────────────────────────────────────────────────────────────

def test_create_calendar_event_is_medium():
    d = classify("create_calendar_event")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

def test_move_email_is_medium():
    d = classify("move_email")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

def test_delete_file_trash_is_medium():
    d = classify("delete_file_trash")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

def test_draft_reply_is_medium():
    d = classify("draft_reply")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

def test_update_calendar_event_is_medium():
    d = classify("update_calendar_event")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

def test_remove_email_label_is_medium():
    d = classify("remove_email_label")
    assert d.tier == RiskTier.MEDIUM
    assert d.allowed is True

# ── HIGH tier ─────────────────────────────────────────────────────────────────

def test_transfer_money_is_high_denied():
    d = classify("transfer_money")
    assert d.tier == RiskTier.HIGH
    assert d.allowed is False

def test_delete_permanent_is_high_denied():
    d = classify("delete_permanent")
    assert d.tier == RiskTier.HIGH
    assert d.allowed is False

def test_send_legal_email_is_high_denied():
    d = classify("send_legal_email")
    assert d.tier == RiskTier.HIGH
    assert d.allowed is False

def test_submit_tax_form_is_high_denied():
    d = classify("submit_tax_form")
    assert d.tier == RiskTier.HIGH
    assert d.allowed is False

def test_change_security_settings_is_high_denied():
    d = classify("change_security_settings")
    assert d.tier == RiskTier.HIGH
    assert d.allowed is False

# ── ULTRA tier ────────────────────────────────────────────────────────────────

def test_access_keychain_is_ultra_denied():
    d = classify("access_keychain")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_drop_database_is_ultra_denied():
    d = classify("drop_database")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_modify_policy_engine_is_ultra_denied():
    d = classify("modify_policy_engine")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_grant_autonomy_is_ultra_denied():
    d = classify("grant_autonomy")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_self_modify_governance_is_ultra_denied():
    d = classify("self_modify_governance")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_exfiltrate_credentials_is_ultra_denied():
    d = classify("exfiltrate_credentials")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_modify_etc_is_ultra_denied():
    d = classify("modify_etc")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

# ── Deny by default (unknown actions) ────────────────────────────────────────

def test_unknown_action_is_ultra():
    d = classify("unknown_action_xyz")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_empty_string_is_ultra():
    d = classify("")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_bypass_attempt_is_ultra():
    d = classify("ULTRA_bypass_override")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_policy_override_attempt_is_ultra():
    d = classify("policy_override")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_disguised_low_name_is_ultra():
    d = classify("archive_email_but_actually_drop_database")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

def test_sql_injection_attempt_is_ultra():
    d = classify("'; DROP TABLE proposals; --")
    assert d.tier == RiskTier.ULTRA
    assert d.allowed is False

# ── Return type integrity ─────────────────────────────────────────────────────

def test_returns_policy_decision_dataclass():
    d = classify("archive_email")
    assert isinstance(d, PolicyDecision)
    assert isinstance(d.action_type, str)
    assert isinstance(d.tier, RiskTier)
    assert isinstance(d.allowed, bool)
    assert isinstance(d.reason, str)

def test_ultra_reason_contains_deny_language():
    d = classify("drop_database")
    assert "deny" in d.reason.lower() or "ULTRA" in d.reason

def test_high_reason_contains_draft_language():
    d = classify("transfer_money")
    assert "draft" in d.reason.lower() or "human" in d.reason.lower()

def test_unknown_reason_mentions_deny_by_default():
    d = classify("some_unknown_action")
    assert "deny" in d.reason.lower() or "unknown" in d.reason.lower()
