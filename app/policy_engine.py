"""
Policy engine — the ONLY authority for risk classification.
Every action must pass through here before execution.
Unknown actions = ULTRA (hard deny). No exceptions.
"""

from enum import Enum
from dataclasses import dataclass

class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    ULTRA = "ULTRA"

# Explicit allow-list with risk tiers. Anything not here = ULTRA.
_ACTION_RISK: dict[str, RiskTier] = {
    # LOW — auto-execute (reversible, local, non-destructive)
    "archive_email": RiskTier.LOW,
    "mark_read": RiskTier.LOW,
    "add_metadata_tag": RiskTier.LOW,
    "rebuild_index": RiskTier.LOW,
    "clean_temp_files": RiskTier.LOW,
    "rerun_index": RiskTier.LOW,
    # OS / UI actions — read-only side effects, instantly reversible
    "open_finder": RiskTier.LOW,
    "open_app": RiskTier.LOW,
    "open_url": RiskTier.LOW,
    "web_search": RiskTier.LOW,
    # macOS automation (MAC-03) — read-only or informational side effects
    "open_contacts_card": RiskTier.LOW,
    "set_volume": RiskTier.LOW,
    "get_frontmost_app": RiskTier.LOW,
    "show_notification": RiskTier.LOW,
    # INFO-01 News
    "open_news_article": RiskTier.LOW,
    # HOME-02 Hue — LOW (instantly reversible)
    "hue_turn_on": RiskTier.LOW,
    "hue_turn_off": RiskTier.LOW,
    "hue_set_brightness": RiskTier.LOW,
    "hue_set_color": RiskTier.LOW,
    "hue_set_scene": RiskTier.LOW,
    # MEDIUM — approve → execute (reversible, modifies real systems)
    "run_shortcut": RiskTier.MEDIUM,
    "create_note": RiskTier.MEDIUM,
    "append_to_note": RiskTier.MEDIUM,
    "move_email": RiskTier.MEDIUM,
    "remove_email_label": RiskTier.MEDIUM,
    "create_calendar_event": RiskTier.MEDIUM,
    "update_calendar_event": RiskTier.MEDIUM,
    "delete_file_trash": RiskTier.MEDIUM,
    "draft_reply": RiskTier.MEDIUM,
    # HIGH — draft only, human finalizes (irreversible or financial)
    "transfer_money": RiskTier.HIGH,
    "submit_tax_form": RiskTier.HIGH,
    "send_legal_email": RiskTier.HIGH,
    "delete_permanent": RiskTier.HIGH,
    "change_security_settings": RiskTier.HIGH,
    # ULTRA — hard deny always (core system, secrets, irreversible destruction)
    "access_keychain": RiskTier.ULTRA,
    "exfiltrate_credentials": RiskTier.ULTRA,
    "modify_etc": RiskTier.ULTRA,
    "drop_database": RiskTier.ULTRA,
    "modify_policy_engine": RiskTier.ULTRA,
    "grant_autonomy": RiskTier.ULTRA,
    "self_modify_governance": RiskTier.ULTRA,
}

@dataclass
class PolicyDecision:
    action_type: str
    tier: RiskTier
    allowed: bool      # True = LOW or MEDIUM (execution rules differ). False = HIGH or ULTRA.
    reason: str

def classify(action_type: str) -> PolicyDecision:
    """
    Classify action_type into a risk tier. Unknown = ULTRA.
    This is the ONLY place policy decisions are made.
    Never call this from UI directly — always via the proposal flow.
    """
    tier = _ACTION_RISK.get(action_type, RiskTier.ULTRA)

    if tier == RiskTier.ULTRA:
        if action_type not in _ACTION_RISK:
            reason = f"Unknown action '{action_type}' — denied by default (ULTRA, deny-by-default rule)"
        else:
            reason = f"Action '{action_type}' is ULTRA — hard deny, no override"
        return PolicyDecision(action_type=action_type, tier=tier, allowed=False, reason=reason)

    if tier == RiskTier.HIGH:
        return PolicyDecision(
            action_type=action_type, tier=tier, allowed=False,
            reason=f"Action '{action_type}' is HIGH risk — draft only, human finalizes, no auto-execution"
        )

    # LOW and MEDIUM are allowed (but execution rules differ: LOW=auto, MEDIUM=requires approval)
    return PolicyDecision(
        action_type=action_type, tier=tier, allowed=True,
        reason=f"Action '{action_type}' classified as {tier.value}"
    )
