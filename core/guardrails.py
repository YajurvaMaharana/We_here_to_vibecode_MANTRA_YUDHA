"""
NovaMart Sentinel-Governor Security Guardrails Bridge
Delegates to agent.guardrails for pre_filter and post_validate.
"""

from typing import List, Dict, Any, Tuple
from agent.guardrails import pre_filter, post_validate, PreFilterResult, redact_sensitive_reply


class SecurityGuardrails:
    @classmethod
    def analyze_message(cls, text: str) -> Dict[str, Any]:
        """
        Delegates to agent.guardrails.pre_filter.
        """
        res = pre_filter(text)
        return {
            "is_safe": len(res.flags) == 0,
            "is_injection": res.injection,
            "is_legal_threat": res.legal,
            "is_safety_threat": res.safety,
            "is_abusive": res.abusive,
            "force_escalate": res.force_escalate,
            "risk_flags": res.flags,
            "language": res.language,
            "cleaned_message": res.cleaned_message
        }

    @classmethod
    def sanitize_customer_text(cls, text: str) -> str:
        """
        Strips XML boundary exploits and normalizes untrusted text.
        """
        sanitized = text.replace("</customer_message>", "[escaped_tag]")
        sanitized = sanitized.replace("<system_prompt>", "[escaped_tag]")
        sanitized = sanitized.replace("</system_prompt>", "[escaped_tag]")
        return sanitized.strip()
