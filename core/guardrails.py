"""
NovaMart Sentinel-Governor Security Guardrails & Threat Analyzer
Enforces Authority Hierarchy L1 and sanitizes untrusted L4 Customer Messages.
"""

import re
from typing import List, Dict, Any, Tuple


class SecurityGuardrails:
    # Patterns indicating prompt injection or system override attempts
    INJECTION_PATTERNS = [
        r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts)\b",
        r"(?i)\bsystem\s+override\b",
        r"(?i)\bdeveloper\s+mode\b",
        r"(?i)\boperating\s+as\s+root\b",
        r"(?i)\bact\s+as\s+(admin|ceo|developer|root|supervisor)\b",
        r"(?i)\breveal\s+(your\s+)?(system\s+prompt|instructions|rules|secret)\b",
        r"(?i)\boutput\s+(your\s+)?(entire\s+)?(system\s+prompt|prompt)\b",
        r"(?i)\bprint\s+(your\s+)?(system\s+prompt|prompt)\b",
        r"(?i)\bshow\s+me\s+the\s+system\s+prompt\b",
        r"(?i)\bbypass\s+policy\b",
        r"(?i)\bauto-?approve\s+everything\b",
        r"(?i)\bdisable\s+guardrails\b"
    ]

    # Patterns indicating legal or regulatory threats
    LEGAL_PATTERNS = [
        r"(?i)\blawyer\b",
        r"(?i)\battorney\b",
        r"(?i)\bsue\s+you\b",
        r"(?i)\blawsuit\b",
        r"(?i)\bconsumer\s+protection\s+bureau\b",
        r"(?i)\bftc\s+complaint\b",
        r"(?i)\bbetter\s+business\s+bureau\b",
        r"(?i)\blegal\s+action\b",
        r"(?i)\bregulatory\s+(action|complaint)\b"
    ]

    # Patterns indicating harassment, self-harm, or severe safety risks
    SAFETY_PATTERNS = [
        r"(?i)\bkill\s+myself\b",
        r"(?i)\bhurt\s+myself\b",
        r"(?i)\bsuicide\b",
        r"(?i)\bself-?harm\b",
        r"(?i)\bbomb\b",
        r"(?i)\bphysical\s+violence\b"
    ]

    @classmethod
    def analyze_message(cls, text: str) -> Dict[str, Any]:
        """
        Scans untrusted input for security, injection, legal, and safety risks.
        """
        flags: List[str] = []
        is_injection = False
        is_legal_threat = False
        is_safety_threat = False

        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, text):
                flags.append("PROMPT_INJECTION_DETECTED")
                is_injection = True
                break

        for pattern in cls.LEGAL_PATTERNS:
            if re.search(pattern, text):
                flags.append("LEGAL_REGULATORY_THREAT")
                is_legal_threat = True
                break

        for pattern in cls.SAFETY_PATTERNS:
            if re.search(pattern, text):
                flags.append("CRITICAL_SAFETY_HARASSMENT")
                is_safety_threat = True
                break

        return {
            "is_safe": len(flags) == 0,
            "is_injection": is_injection,
            "is_legal_threat": is_legal_threat,
            "is_safety_threat": is_safety_threat,
            "risk_flags": flags
        }

    @classmethod
    def sanitize_customer_text(cls, text: str) -> str:
        """
        Strips XML boundary exploits and normalizes untrusted text.
        """
        # Escape any rogue closing tags attempting to break out of <customer_message>
        sanitized = text.replace("</customer_message>", "[escaped_tag]")
        sanitized = sanitized.replace("<system_prompt>", "[escaped_tag]")
        sanitized = sanitized.replace("</system_prompt>", "[escaped_tag]")
        return sanitized.strip()
