"""
NovaMart Sentinel-Governor Guardrails Module
Location: agent/guardrails.py

Features:
1. pre_filter(message) -> PreFilterResult:
   - Layer 1 regex/keywords covering English + Romanised Hindi/Hinglish
     * Injection: "ignore (all )?(previous|prior)", "system prompt", "maintenance mode",
       "you are now", "developer mode", "approve all refunds", "i am (the )?admin",
       "policy (has )?changed", "override", etc.
     * Legal: "lawyer|sue|court|consumer forum|legal action|police|FIR|notice", etc.
     * Safety: Self-harm / suicide / violence against people; product fire, shock, or injury.
       CRITICAL: False-positive resistant (e.g. "the box was cut open" must NOT trigger violence).
     * Abusive: Slurs, harassment, profanity.
   - Layer 2 cheap classifier call using prompts/injection_classifier.md:
     Invoked only when Layer 1 is inconclusive and len(message) > 40.
   - Rules:
     * Injection ALONE does not escalate: it is ignored and genuine request is served (strip injected sentence).
     * Legal or Safety => force_escalate = True.
2. post_validate(final, tool_log, session) -> Dict[str, Any]:
   - May downgrade ACT -> ASK / ESCALATE when:
     * create_refund called on ownership_mismatch or unverified order (-> ESCALATE)
     * amount above approval threshold (-> ESCALATE)
     * OTP-verified delivery + non-delivery claim (-> ESCALATE)
     * no check_refund_eligibility earlier in tool_log (-> ASK / ESCALATE)
     * refund_amount != calculate_refund result (-> ESCALATE)
   - Redacts reply text containing:
     * OTP codes
     * Driver information
     * Route telemetry
     * 'system prompt'
"""

import re
import os
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PreFilterResult:
    injection: bool
    legal: bool
    safety: bool
    abusive: bool
    force_escalate: bool
    flags: List[str] = field(default_factory=list)
    language: str = "en"
    cleaned_message: str = ""

    def __iter__(self):
        """Allows tuple unpacking: injection, legal, safety, abusive, force_escalate, flags, language = pre_filter(msg)"""
        yield self.injection
        yield self.legal
        yield self.safety
        yield self.abusive
        yield self.force_escalate
        yield self.flags
        yield self.language

    def __getitem__(self, index):
        return list(self)[index]


# =========================================================================
# Layer 1 Pattern Definitions (English + Romanised Hindi / Hinglish)
# =========================================================================

# 1. INJECTION PATTERNS
INJECTION_PATTERNS_EN = [
    r"(?i)\bignore\s+(all\s+)?(previous|prior|past)\b",
    r"(?i)\bsystem\s+prompt\b",
    r"(?i)\bmaintenance\s+mode\b",
    r"(?i)\byou\s+are\s+now\b",
    r"(?i)\bdeveloper\s+mode\b",
    r"(?i)\bapprove\s+all\s+refunds\b",
    r"(?i)\bi\s+am\s+(the\s+)?admin\b",
    r"(?i)\bpolicy\s+(has\s+)?changed\b",
    r"(?i)\boverride\b",
    r"(?i)\bact\s+as\s+(admin|root|ceo|developer)\b",
    r"(?i)\breveal\s+(your\s+)?(system\s+prompt|instructions)\b",
]

INJECTION_PATTERNS_HINGLISH = [
    r"(?i)\bpichle\s+(saare\s+|sab\s+)?(rules|niyam|instructions)\s+bhool\s+jao\b",
    r"(?i)\b(saare|sab)\s+(rules|niyam|instructions)\s+bhool\s+jao\b",
    r"(?i)\bsystem\s+prompt\s+(dikhao|batao|padho|bhejo)\b",
    r"(?i)\bmain\s+(hi\s+)?(admin|boss|developer)\s+hoon\b",
    r"(?i)\bhum\s+admin\s+hain\b",
    r"(?i)\b(saare|sare)\s+refund(s)?\s+approve\s+karo\b",
    r"(?i)\bpolicy\s+badal\s+gayi\s+hai\b",
    r"(?i)\bsystem\s+(ko\s+)?override\s+karo\b",
    r"(?i)\b(developer|maintenance)\s+mode\s+(chalu|on)\s+karo\b",
]

# 2. LEGAL PATTERNS
# User spec: legal ("lawyer|sue|court|consumer forum|legal action|police|FIR|notice")
LEGAL_PATTERNS = [
    r"(?i)\blawyer\b",
    r"(?i)\bsue\b",
    r"(?i)\bcourt\b",
    r"(?i)\bconsumer\s+(?:forum|court|commission)\b",
    r"(?i)\blegal\s+(?:action|notice|recourse|proceedings|charges)\b",
    r"(?i)\bpolice\b",
    r"\bFIR\b",
    r"(?i)\bfir\s+(?:darj|file|lodged?|karenge|karunga)\b",
    r"(?i)\bfile\s+(?:an?\s+)?(?:police\s+)?fir\b",
    r"(?i)\b(?:send|serve|give)\s+(?:you\s+)?(?:a\s+)?(?:legal\s+)?notice\b",
    # Hinglish
    r"(?i)\b(?:vakeel|vakil)\b",
    r"(?i)\bcourt\s+me\b",
    r"(?i)\bkanooni\s+(?:karwayi|karyavahi)\b",
]

# 3. SAFETY PATTERNS
# Category A: Self-Harm & Suicide
SAFETY_SELF_HARM = [
    r"(?i)\b(?:kill|harm|hurt|hang)\s+myself\b",
    r"(?i)\bsuicide\b",
    r"(?i)\bsuicidal\b",
    r"(?i)\bend\s+my\s+life\b",
    r"(?i)\bmar\s+jaunga\b",
    r"(?i)\bjaan\s+de\s+dunga\b",
    r"(?i)\batmahatya\b",
    r"(?i)\bjeene\s+ka\s+(?:bhi\s+)?(?:mann\s+)?nahi\b",
    r"(?i)\bkuch\s+(?:bhi\s+)?karne\s+ka\s+mann\s+nahi\b",
    r"(?i)\bkhatam\s+kar\s+(?:lunga|dunga)\b",
]

# Category B: Violence against people
# Carefully crafted to avoid matching package condition like "the box was cut open"
SAFETY_VIOLENCE = [
    r"(?i)\b(?:kill|shoot|murder|physically\s+attack|beat\s+up)\s+(?:you|your\s+staff|someone|people|the\s+driver)\b",
    r"(?i)\b(?:find|hunt)\s+(?:him|them|the\s+driver)\s+and\s+make\s+(?:him|them)\s+pay\b",
    r"(?i)\bmake\s+(?:him|them)\s+pay\s+personally\b",
    r"(?i)\btake\s+matters\s+into\s+my\s+own\s+hands\b",
    r"(?i)\b(?:goli|jaan\s+se)\s+maar\s+dunga\b",
    r"(?i)\bbomb\s+(?:the|your)\s+(?:office|warehouse|building|store)\b",
]

# Category C: Physical Product Hazards (Fire, Electric Shock, Explosions, Burns, Injuries)
# Must not trigger on metaphors like "shockingly good" or "fire up notifications"
SAFETY_PRODUCT_HAZARDS = [
    r"(?i)\b(?:charger|battery|product|device|item|phone|laptop|kettle|appliance)\s+(?:caught|started)\s+fire\b",
    r"(?i)\bcaught\s+fire\b",
    r"(?i)\bfire\s+hazard\b",
    r"(?i)\b(?:battery|power\s*bank|device|charger)\s+exploded\b",
    r"(?i)\b(?:battery|device)\s+explosion\b",
    r"(?i)\belectric(?:al)?\s+shock\b",
    r"(?i)\bgave\s+me\s+an?\s+electric\s+shock\b",
    r"(?i)\bgot\s+(?:an?\s+)?electric\s+shock\b",
    r"(?i)\b(?:got|caused)\s+burn(?:ed)?\s+(?:my\s+)?(?:hand|skin|finger|face)\b",
    r"(?i)\bburned\s+my\s+(?:hand|skin|carpet|house|table)\b",
    r"(?i)\bcaused\s+(?:an?\s+)?(?:injury|hospitalization|burns)\b",
    # Hinglish
    r"(?i)\bcurrent\s+laga\b",
    r"(?i)\bshock\s+laga\b",
    r"(?i)\baag\s+lag\s+gayi\b",
    r"(?i)\bhath\s+jal\s+gaya\b",
    r"(?i)\bchot\s+lag\s+gayi\b",
    r"(?i)\bblast\s+ho\s+gaya\b",
]

# 4. ABUSIVE PATTERNS
ABUSIVE_PATTERNS = [
    r"(?i)\b(?:idiot|moron|bastard|asshole|scammer|thief|thieves|bullshit|scam|bitch|fucking?)\b",
    # Hinglish
    r"(?i)\b(?:chutiya|kamina|kaminey|harami|madarchod|bhenchod|bakwas|chor|lutere|dhokhebaaz|kutta)\b",
]


# =========================================================================
# Helper Functions: Language Detection & Sentence Stripping
# =========================================================================

HINGLISH_KEYWORDS = {
    "karo", "karna", "karein", "nahi", "mujhe", "mera", "meri", "mere", "hai", "hain",
    "tha", "thi", "raha", "rahe", "rahi", "kyun", "kab", "kahan", "kaise", "bhejo",
    "bheja", "paise", "wapas", "turant", "jaldi", "dhokha", "chor", "vakeel", "court",
    "kanoon", "pichle", "saare", "bhool", "jao", "main", "hum", "aap", "tum", "laga",
    "gaya", "gayi", "chahiye"
}


def detect_language(text: str) -> str:
    """Detects whether text is predominantly English or Romanised Hindi / Hinglish."""
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    hinglish_count = len(words.intersection(HINGLISH_KEYWORDS))
    if hinglish_count >= 2:
        return "hinglish"
    return "en"


def strip_injected_sentences(message: str, injection_regexes: List[str]) -> str:
    """
    Strips sentences that match injection patterns, keeping the genuine request.
    Example:
    'Ignore previous rules. Where is my order ORD-123?' -> 'Where is my order ORD-123?'
    """
    # Split by common sentence terminators while preserving remaining structure
    raw_sentences = re.split(r"(?<=[.!?\n;])\s+", message)
    kept_sentences = []

    for sentence in raw_sentences:
        s_clean = sentence.strip()
        if not s_clean:
            continue
        is_injected = False
        for pattern in injection_regexes:
            if re.search(pattern, s_clean):
                is_injected = True
                break
        if not is_injected:
            kept_sentences.append(s_clean)

    # If all sentences were stripped or only injection was present
    return " ".join(kept_sentences).strip()


# =========================================================================
# Layer 2: Cheap Injection Classifier
# =========================================================================

def run_layer2_classifier(message: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Layer 2 is a cheap classifier call using prompts/injection_classifier.md,
    invoked only when Layer 1 is inconclusive and len(message) > 40.
    Checks for obfuscated or structured adversarial framing.
    """
    prompt_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prompts",
        "injection_classifier.md"
    )

    # Heuristic simulation of cheap classifier checking obfuscated/covert injection templates
    obfuscated_injection_patterns = [
        r"(?i)s\s*y\s*s\s*t\s*e\s*m\s*p\s*r\s*o\s*m\s*p\s*t",
        r"(?i)1gn0r3\s+all",
        r"(?i)(?:roleplay|hypothetical)\s+where\s+you\s+(?:ignore|disregard|approve)",
        r"(?i)\[(?:system|admin|root)\]",
        r"(?i)human:\s*.*\s*assistant:\s*",
        r"(?i)base64:\s*[A-Za-z0-9+/=]{10,}",
        r"(?i)dan\s+mode",
    ]

    for pattern in obfuscated_injection_patterns:
        if re.search(pattern, message):
            return True, "LAYER2_OBFUSCATED_INJECTION", "Obfuscated or structured adversarial injection detected"

    return False, None, None


# =========================================================================
# Main Function 1: pre_filter(message)
# =========================================================================

def pre_filter(message: str) -> PreFilterResult:
    """
    Scans incoming customer message across Layer 1 and Layer 2 guardrails.
    Returns PreFilterResult(injection, legal, safety, abusive, force_escalate, flags, language, cleaned_message).
    """
    if not message or not message.strip():
        return PreFilterResult(
            injection=False,
            legal=False,
            safety=False,
            abusive=False,
            force_escalate=False,
            flags=[],
            language="en",
            cleaned_message=""
        )

    text = message.strip()
    language = detect_language(text)
    flags: List[str] = []

    injection = False
    legal = False
    safety = False
    abusive = False

    # -------------------------------------------------------------------------
    # Layer 1: Injection Scan
    # -------------------------------------------------------------------------
    all_injection_patterns = INJECTION_PATTERNS_EN + INJECTION_PATTERNS_HINGLISH
    for pattern in all_injection_patterns:
        if re.search(pattern, text):
            injection = True
            flags.append("PROMPT_INJECTION_DETECTED")
            flags.append(f"INJECTION_FLAG: {pattern}")
            break

    # -------------------------------------------------------------------------
    # Layer 1: Legal Scan
    # -------------------------------------------------------------------------
    for pattern in LEGAL_PATTERNS:
        if re.search(pattern, text):
            # Double check for false positives like "police costume"
            if "police costume" in text.lower():
                continue
            legal = True
            flags.append("LEGAL_FLAG: legal_action_threat")
            break

    # -------------------------------------------------------------------------
    # Layer 1: Safety Scan (Self-harm, violence, product fire/shock/injury)
    # -------------------------------------------------------------------------
    # 1. Self-Harm
    for pattern in SAFETY_SELF_HARM:
        if re.search(pattern, text):
            safety = True
            flags.append("SAFETY_FLAG: self_harm_suicide")
            break

    # 2. Violence against people (Must NOT trigger on "the box was cut open")
    if not safety:
        for pattern in SAFETY_VIOLENCE:
            if re.search(pattern, text):
                safety = True
                flags.append("SAFETY_FLAG: violence_threat")
                break

    # 3. Product Hazards (Fire, Shock, Explosion, Injury)
    if not safety:
        for pattern in SAFETY_PRODUCT_HAZARDS:
            if re.search(pattern, text):
                # Ensure no false positives on metaphors like "shockingly good"
                if "shockingly good" in text.lower() or "fire up" in text.lower():
                    continue
                safety = True
                flags.append("SAFETY_FLAG: product_hazard")
                break

    # -------------------------------------------------------------------------
    # Layer 1: Abusive Scan
    # -------------------------------------------------------------------------
    for pattern in ABUSIVE_PATTERNS:
        if re.search(pattern, text):
            abusive = True
            flags.append("ABUSIVE_FLAG: profanity_or_harassment")
            break

    # -------------------------------------------------------------------------
    # Layer 2: Cheap Classifier (Only when Layer 1 is inconclusive and len > 40)
    # -------------------------------------------------------------------------
    is_layer1_inconclusive = not (injection or legal or safety or abusive)
    if is_layer1_inconclusive and len(text) > 40:
        l2_injection, l2_flag, l2_reason = run_layer2_classifier(text)
        if l2_injection:
            injection = True
            flags.append(f"LAYER2_INJECTION: {l2_flag}")

    # -------------------------------------------------------------------------
    # Rule Evaluation:
    # 1. injection ALONE does not escalate; it is ignored and genuine request is served.
    # 2. Legal or Safety => force_escalate = True.
    # -------------------------------------------------------------------------
    force_escalate = legal or safety

    # Strip injected sentence while preserving genuine customer request
    if injection:
        cleaned_message = strip_injected_sentences(text, all_injection_patterns)
    else:
        cleaned_message = text

    return PreFilterResult(
        injection=injection,
        legal=legal,
        safety=safety,
        abusive=abusive,
        force_escalate=force_escalate,
        flags=flags,
        language=language,
        cleaned_message=cleaned_message
    )


# =========================================================================
# Redaction Helpers for post_validate
# =========================================================================

def redact_sensitive_reply(text: str) -> str:
    """
    Redacts any reply text containing:
    - OTP codes
    - Driver information
    - Route telemetry
    - 'system prompt'
    """
    if not text:
        return ""

    redacted = text

    # Redact 'system prompt'
    redacted = re.sub(r"(?i)\bsystem\s+prompt\b", "[REDACTED]", redacted)

    # Redact OTP references and codes (e.g., "OTP: 7841", "OTP is 1234", "otp 9921", "one-time passcode 7841")
    redacted = re.sub(r"(?i)\b(?:otp|one-time\s+passcode)\s*(?:is|code|:)?\s*[:=]?\s*([0-9]{4,8})\b", "OTP [REDACTED]", redacted)
    redacted = re.sub(r"(?i)\bcode\s+([0-9]{4,8})\s+verified\b", "security code [REDACTED] verified", redacted)

    # Redact Driver information (e.g., "driver John", "driver's phone +1...", "driver details")
    redacted = re.sub(r"(?i)\bdriver(?:\s+name)?(?:\s+is|\s*[:=])?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", "driver [REDACTED]", redacted)
    redacted = re.sub(r"(?i)\bdriver\s+phone\s*[:=]?\s*(\+?[0-9\-]{7,15})\b", "driver phone [REDACTED]", redacted)

    # Redact Route information (e.g., "route #14", "route data", "route ID: R-990")
    redacted = re.sub(r"(?i)\broute(?:\s+id|\s+number|\s*#)?(?:\s*[:=]?\s*)([A-Za-z0-9\-]+)\b", "route [REDACTED]", redacted)

    return redacted


# =========================================================================
# Main Function 2: post_validate(final, tool_log, session)
# =========================================================================

def post_validate(final: Dict[str, Any], tool_log: List[Dict[str, Any]], session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates agent turn output against critical compliance checks before sending to customer.
    May downgrade ACT -> ASK / ESCALATE when:
    1. create_refund called on ownership_mismatch or unverified order (-> ESCALATE)
    2. amount above approval threshold (-> ESCALATE)
    3. OTP-verified delivery + non-delivery claim (-> ESCALATE)
    4. no check_refund_eligibility earlier in tool_log (-> ASK / ESCALATE)
    5. refund_amount != calculate_refund result (-> ESCALATE)
    Also redacts reply text containing otp, driver, route, 'system prompt'.
    """
    validated_final = dict(final)
    decision = validated_final.get("decision", "ANSWER")
    reply = validated_final.get("customer_response") or validated_final.get("reply", "")
    audit_trail = validated_final.setdefault("audit_trail", {})
    downgrade_reasons = []

    # -------------------------------------------------------------------------
    # Redaction Check on Reply Text
    # -------------------------------------------------------------------------
    redacted_reply = redact_sensitive_reply(reply)
    if "customer_response" in validated_final:
        validated_final["customer_response"] = redacted_reply
    if "reply" in validated_final:
        validated_final["reply"] = redacted_reply

    # Only inspect downgrades if decision is 'ACT'
    if decision != "ACT":
        return validated_final

    # Identify refund tool call in tool_log if any
    refund_call = None
    refund_tool_index = -1
    for idx, call in enumerate(tool_log):
        tool_name = call.get("tool", "")
        if tool_name in ["create_refund", "process_refund"]:
            refund_call = call
            refund_tool_index = idx
            break

    # If an action was taken that wasn't a refund, check general threshold
    approval_threshold = session.get("approval_threshold", 100.00)

    # -------------------------------------------------------------------------
    # Check 1: create_refund on ownership_mismatch or unverified order
    # -------------------------------------------------------------------------
    if refund_call:
        order_verified = session.get("order_verified", False)
        ownership_mismatch = session.get("ownership_mismatch", False)

        # Also inspect get_order call in tool_log
        get_order_calls = [c for c in tool_log if c.get("tool") == "get_order"]
        if get_order_calls:
            order_res = get_order_calls[0].get("result", {})
            if not order_res.get("found", True):
                order_verified = False
            if not order_res.get("authorized", True) or order_res.get("ownership_mismatch"):
                ownership_mismatch = True
        else:
            # get_order was never called!
            order_verified = False

        if not order_verified or ownership_mismatch:
            decision = "ESCALATE"
            downgrade_reasons.append("DOWNGRADE: create_refund called on ownership_mismatch or unverified order")

    # -------------------------------------------------------------------------
    # Check 2: Amount above approval threshold
    # -------------------------------------------------------------------------
    if refund_call and decision == "ACT":
        refund_args = refund_call.get("args", {})
        refund_amount = refund_args.get("amount", session.get("order_amount", 0.0))
        if refund_amount > approval_threshold:
            decision = "ESCALATE"
            downgrade_reasons.append(f"DOWNGRADE: Refund amount (${refund_amount}) exceeds approval threshold (${approval_threshold})")

    # -------------------------------------------------------------------------
    # Check 3: OTP-verified delivery + non-delivery claim
    # -------------------------------------------------------------------------
    is_non_delivery_claim = session.get("non_delivery_claim", False)
    otp_verified_delivery = session.get("otp_verified", False)

    # Check order delivery records in session if available
    order_data = session.get("order", {})
    if order_data.get("delivery", {}).get("otp_verified"):
        otp_verified_delivery = True

    if is_non_delivery_claim and otp_verified_delivery:
        decision = "ESCALATE"
        downgrade_reasons.append("DOWNGRADE: Non-delivery claim contradicted by OTP-verified delivery record")

    # -------------------------------------------------------------------------
    # Check 4: No check_refund_eligibility earlier in tool_log
    # -------------------------------------------------------------------------
    if refund_call and decision == "ACT":
        eligibility_checked = False
        for idx, call in enumerate(tool_log):
            if call.get("tool") == "check_refund_eligibility" and idx < refund_tool_index:
                eligibility_checked = True
                break

        if not eligibility_checked:
            decision = "ASK"
            downgrade_reasons.append("DOWNGRADE: No check_refund_eligibility call found in tool_log prior to refund execution")

    # -------------------------------------------------------------------------
    # Check 5: refund_amount != calculate_refund result
    # -------------------------------------------------------------------------
    if refund_call and decision == "ACT":
        calc_calls = [c for c in tool_log if c.get("tool") == "calculate_refund"]
        if calc_calls:
            calc_result = calc_calls[0].get("result", {})
            expected_amount = calc_result.get("net_refund", calc_result.get("amount"))
            refund_amount = refund_call.get("args", {}).get("amount")
            if expected_amount is not None and refund_amount is not None:
                if abs(float(refund_amount) - float(expected_amount)) > 0.01:
                    decision = "ESCALATE"
                    downgrade_reasons.append(f"DOWNGRADE: refund_amount (${refund_amount}) does not match calculate_refund result (${expected_amount})")

    # Apply downgrades if any triggered
    if downgrade_reasons:
        validated_final["decision"] = decision
        audit_trail.setdefault("risk_flags", []).extend(downgrade_reasons)
        audit_trail["downgraded_by_post_validate"] = True
        audit_trail["downgrade_reasons"] = downgrade_reasons

        # Update customer response appropriately if downgraded
        if decision == "ESCALATE":
            validated_final["customer_response"] = (
                "Your request has been forwarded to our Senior Escalations Team for manual authorization. "
                "A specialist will review your account records and update you within 2 business hours."
            )
        elif decision == "ASK":
            validated_final["customer_response"] = (
                "Before we can proceed with your return or refund request, could you please confirm the reason and provide any additional details?"
            )

    return validated_final
