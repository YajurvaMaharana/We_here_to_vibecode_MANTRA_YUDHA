"""
NovaMart Sentinel-Governor Core Data Models & Schemas
"""

from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime, timezone

DecisionType = Literal["ANSWER", "ASK", "ACT", "ESCALATE"]
ClaimStatus = Literal["VERIFIED_MATCH", "CLAIM_MISMATCH", "UNVERIFIED", "REQUIRES_EVIDENCE"]


@dataclass
class CustomerMessage:
    raw_text: str
    customer_id: str
    session_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class IntentExtraction:
    primary_intent: str
    secondary_intents: List[str] = field(default_factory=list)
    extracted_order_id: Optional[str] = None
    extracted_item_id: Optional[str] = None
    claim_summary: str = ""
    requested_action: Optional[str] = None


@dataclass
class ClaimVerification:
    claim_text: str
    database_truth: str
    status: ClaimStatus
    discrepancy_details: Optional[str] = None


@dataclass
class PolicyCheckResult:
    policy_category: str
    return_window_days: int
    days_elapsed: Optional[int]
    within_window: bool
    requires_photo: bool
    photo_on_file: bool
    auto_approval_cap: float
    order_amount: float
    exceeds_cap: bool
    restocking_fee: float = 0.0
    net_eligible_refund: float = 0.0


@dataclass
class AuditTrail:
    turn_id: str
    customer_id: str
    session_id: str
    detected_intents: List[str]
    claims_verified: List[Dict[str, Any]]
    policy_checked: Optional[Dict[str, Any]]
    decision: DecisionType
    decision_rationale: str
    tools_executed: List[Dict[str, Any]]
    risk_flags: List[str]
    execution_time_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GovernorTurnOutput:
    decision: DecisionType
    customer_response: str
    audit_trail: Dict[str, Any]
    steps_trace: List[Dict[str, Any]]
