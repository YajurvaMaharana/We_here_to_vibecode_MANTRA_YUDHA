"""
NovaMart Sentinel-Governor Core Reasoning & Decision Engine
Implements the 8-step pipeline and enforces the L1-L4 Authority Hierarchy.
"""

import re
import time
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from core.models import (
    CustomerMessage,
    IntentExtraction,
    ClaimVerification,
    PolicyCheckResult,
    AuditTrail,
    GovernorTurnOutput,
    DecisionType
)
from core.guardrails import SecurityGuardrails
from core.verifier import ClaimVerifier
from tools.registry import ToolRegistry


class SentinelGovernor:
    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.tools = tool_registry if tool_registry is not None else ToolRegistry()

    def process_turn(self, raw_customer_message: str, customer_id: str, session_id: Optional[str] = None) -> GovernorTurnOutput:
        start_time = time.time()
        turn_id = f"TURN-{uuid.uuid4().hex[:6].upper()}"
        session_id = session_id or f"SESS-{uuid.uuid4().hex[:6].upper()}"
        steps_trace: List[Dict[str, Any]] = []
        risk_flags: List[str] = []
        tools_called_in_turn: List[Dict[str, Any]] = []

        # =========================================================================
        # SECURITY & GUARDRAILS SCAN (Authority Hierarchy L1)
        # =========================================================================
        security_analysis = SecurityGuardrails.analyze_message(raw_customer_message)
        if security_analysis["risk_flags"]:
            risk_flags.extend(security_analysis["risk_flags"])

        clean_text = SecurityGuardrails.sanitize_customer_text(raw_customer_message)

        # Immediate Defense against Prompt Injection & Override Attempts
        if security_analysis["is_injection"]:
            steps_trace.append({
                "step": "L1_SECURITY_DEFENSE",
                "status": "ATTACK_INTERCEPTED",
                "details": "L1 System Prompt violation intercepted. Customer message attempted prompt injection or authority override."
            })
            customer_resp = (
                "I cannot fulfill this request. I am the NovaMart Customer Support Agent, "
                "and I assist only with verified orders and customer service inquiries. "
                "Please provide your order number if you require assistance with an existing purchase."
            )
            audit = {
                "turn_id": turn_id,
                "customer_id": customer_id,
                "session_id": session_id,
                "detected_intents": ["prompt_injection_attempt"],
                "claims_verified": [],
                "policy_checked": None,
                "decision": "ANSWER",
                "decision_rationale": "Authority Hierarchy L1: Customer tried to alter operating constraints or extract system prompts. Defended without acting.",
                "tools_executed": [],
                "risk_flags": risk_flags,
                "execution_time_ms": round((time.time() - start_time) * 1000, 2)
            }
            self.tools.finalize("ANSWER", customer_resp, audit)
            return GovernorTurnOutput(
                decision="ANSWER",
                customer_response=customer_resp,
                audit_trail=audit,
                steps_trace=steps_trace
            )

        # =========================================================================
        # STEP 1: UNDERSTAND (Detect distinct intents and entities)
        # =========================================================================
        detected_intents = self._extract_intents(clean_text)
        extracted_order_id = self._extract_order_id(clean_text)
        steps_trace.append({
            "step": "1_UNDERSTAND",
            "detected_intents": detected_intents,
            "extracted_order_id": extracted_order_id,
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 2: CONTEXT (Profile, order history, active tickets)
        # =========================================================================
        customer_profile = self.tools.db.get("customers", {}).get(customer_id, {})
        customer_orders = [
            order for order in self.tools.db.get("orders", {}).values()
            if order.get("customer_id") == customer_id
        ]
        trust_score = customer_profile.get("trust_score", 100)
        recent_refund_count = customer_profile.get("recent_refund_count_30d", 0)

        if recent_refund_count >= 2 or trust_score < 50:
            risk_flags.append("HIGH_REFUND_FREQUENCY_RISK")

        steps_trace.append({
            "step": "2_CONTEXT",
            "customer_id": customer_id,
            "customer_name": customer_profile.get("name", "Unknown"),
            "trust_score": trust_score,
            "order_count": len(customer_orders),
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 3: VERIFY (Compare claims with L3 Database Ground Truth)
        # =========================================================================
        order_verification = None
        claims_list: List[ClaimVerification] = []

        if extracted_order_id:
            order_verification = self.tools.get_order(extracted_order_id, customer_id)
            tools_called_in_turn.append({"tool": "get_order", "args": {"order_id": extracted_order_id, "customer_id": customer_id}})
            claims_list = ClaimVerifier.verify_order_claim(customer_id, extracted_order_id, order_verification, clean_text)
        else:
            # If no order ID was given, check customer order count
            claims_list = ClaimVerifier.verify_order_claim(customer_id, None, {}, clean_text)

        steps_trace.append({
            "step": "3_VERIFY",
            "order_lookup": order_verification,
            "claims_matrix": [c.__dict__ for c in claims_list],
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 4: POLICY (Retrieve active policy from L2 layer)
        # =========================================================================
        policy_data = None
        eligibility_data = None
        order_obj = order_verification.get("order") if order_verification and order_verification.get("found") else None

        if order_obj:
            category = order_obj.get("category", "Electronics")
            policy_res = self.tools.get_policy(category)
            tools_called_in_turn.append({"tool": "get_policy", "args": {"category": category}})
            policy_data = policy_res.get("policy")

            if any(i in detected_intents for i in ["refund", "return", "damaged_item"]):
                eligibility_data = self.tools.check_refund_eligibility(
                    order_id=order_obj.get("order_id"),
                    item_id=order_obj.get("items", [{}])[0].get("item_id", ""),
                    reason=clean_text
                )
                tools_called_in_turn.append({
                    "tool": "check_refund_eligibility",
                    "args": {"order_id": order_obj.get("order_id"), "reason": clean_text}
                })

        steps_trace.append({
            "step": "4_POLICY",
            "active_policy": policy_data,
            "eligibility_check": eligibility_data,
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 5: DECIDE (Terminal decision: ANSWER, ASK, ACT, ESCALATE)
        # =========================================================================
        decision, rationale, customer_facing_text = self._make_terminal_decision(
            detected_intents=detected_intents,
            extracted_order_id=extracted_order_id,
            customer_orders=customer_orders,
            order_obj=order_obj,
            order_verification=order_verification,
            claims_list=claims_list,
            policy_data=policy_data,
            eligibility_data=eligibility_data,
            security_analysis=security_analysis,
            risk_flags=risk_flags,
            clean_text=clean_text
        )

        steps_trace.append({
            "step": "5_DECIDE",
            "decision": decision,
            "rationale": rationale,
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 6: ACT (Execute verified state-changing tools under L1-L3)
        # =========================================================================
        action_result = None
        if decision == "ACT":
            if any(i in detected_intents for i in ["refund", "return", "damaged_item"]):
                calc_res = self.tools.calculate_refund(
                    order_id=order_obj["order_id"],
                    item_id=order_obj["items"][0]["item_id"],
                    reason=clean_text
                )
                tools_called_in_turn.append({"tool": "calculate_refund", "args": {"order_id": order_obj["order_id"]}})
                net_amount = calc_res.get("net_refund", order_obj["total_amount"])

                refund_res = self.tools.process_refund(
                    order_id=order_obj["order_id"],
                    item_id=order_obj["items"][0]["item_id"],
                    amount=net_amount,
                    reason="verified_defect_return",
                    destination_account=order_obj.get("payment_method", "Original Payment Method")
                )
                tools_called_in_turn.append({"tool": "process_refund", "args": {"order_id": order_obj["order_id"], "amount": net_amount}})
                action_result = refund_res
                customer_facing_text = (
                    f"I have verified your order #{order_obj['order_id']} and the defect evidence on file. "
                    f"A full refund of ${net_amount:.2f} has been processed back to your original payment method "
                    f"({order_obj.get('payment_method')}). Your transaction reference is {refund_res.get('refund_id')}."
                )

            elif "address_change" in detected_intents:
                new_address = {"street": "Updated Address", "status": "Pending Customer Confirmation"}
                # Try parsing an address if present
                addr_match = re.search(r"to\s+([0-9]+[^,\n]+)", clean_text, re.IGNORECASE)
                if addr_match:
                    new_address["street"] = addr_match.group(1).strip()

                update_res = self.tools.update_shipping_address(order_obj["order_id"], new_address)
                tools_called_in_turn.append({"tool": "update_shipping_address", "args": {"order_id": order_obj["order_id"], "address": new_address}})
                action_result = update_res
                customer_facing_text = (
                    f"I have successfully updated the delivery address for order #{order_obj['order_id']} "
                    f"to '{new_address['street']}'. Since the order is still in processing, the courier will deliver to this new location."
                )

        elif decision == "ESCALATE":
            esc_reason = " | ".join(risk_flags) if risk_flags else "COMPLIANCE_AND_POLICY_THRESHOLD_ESCALATION"
            esc_res = self.tools.escalate_to_human(
                customer_id=customer_id,
                order_id=order_obj.get("order_id") if order_obj else (extracted_order_id or "UNKNOWN"),
                reason=esc_reason,
                verified_data={"order": order_obj, "risk_flags": risk_flags},
                audit_summary=rationale
            )
            tools_called_in_turn.append({"tool": "escalate_to_human", "args": {"reason": esc_reason}})
            action_result = esc_res

        steps_trace.append({
            "step": "6_ACT",
            "decision": decision,
            "action_result": action_result,
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 7: CONFIRM (Verify execution results)
        # =========================================================================
        confirm_status = "CONFIRMED"
        if action_result and not action_result.get("success", True):
            confirm_status = "TOOL_FAILED"
            customer_facing_text = "I encountered an issue verifying the system action. Please wait while a supervisor reviews this."

        steps_trace.append({
            "step": "7_CONFIRM",
            "confirm_status": confirm_status,
            "status": "COMPLETED"
        })

        # =========================================================================
        # STEP 8: FINALIZE (Mandatory compliance and audit payload)
        # =========================================================================
        execution_duration = round((time.time() - start_time) * 1000, 2)
        audit_trail = {
            "turn_id": turn_id,
            "customer_id": customer_id,
            "session_id": session_id,
            "detected_intents": detected_intents,
            "claims_verified": [c.__dict__ for c in claims_list],
            "policy_checked": policy_data,
            "decision": decision,
            "decision_rationale": rationale,
            "tools_executed": tools_called_in_turn,
            "risk_flags": risk_flags,
            "execution_time_ms": execution_duration
        }

        self.tools.finalize(decision, customer_facing_text, audit_trail)
        steps_trace.append({
            "step": "8_FINALIZE",
            "decision": decision,
            "status": "COMPLETED"
        })

        return GovernorTurnOutput(
            decision=decision,
            customer_response=customer_facing_text,
            audit_trail=audit_trail,
            steps_trace=steps_trace
        )

    def _extract_intents(self, text: str) -> List[str]:
        t = text.lower()
        intents = []
        if any(w in t for w in ["refund", "money back", "reimburse"]):
            intents.append("refund")
        if any(w in t for w in ["return", "send back", "exchange"]):
            intents.append("return")
        if any(w in t for w in ["where is", "tracking", "status", "delivery status", "package", "arrived"]):
            intents.append("order_status")
        if any(w in t for w in ["address", "change shipping", "new address", "apartment"]):
            intents.append("address_change")
        if any(w in t for w in ["damaged", "broken", "defective", "distorted", "scratch", "not working", "cracked", "crack"]):
            intents.append("damaged_item")
            intents.append("return")
        if any(w in t for w in ["warranty", "repair", "guarantee"]):
            intents.append("warranty")
        if not intents:
            intents.append("general_inquiry")
        return intents

    def _extract_order_id(self, text: str) -> Optional[str]:
        match = re.search(r"\b(ORD-[0-9]{4,6})\b", text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        # Fallback to plain number if preceded by "order" or "#"
        match_num = re.search(r"(?:order\s*#?|#)\s*([0-9]{4,6})\b", text, re.IGNORECASE)
        if match_num:
            return f"ORD-{match_num.group(1)}"
        return None

    def _make_terminal_decision(
        self,
        detected_intents: List[str],
        extracted_order_id: Optional[str],
        customer_orders: List[Dict[str, Any]],
        order_obj: Optional[Dict[str, Any]],
        order_verification: Optional[Dict[str, Any]],
        claims_list: List[ClaimVerification],
        policy_data: Optional[Dict[str, Any]],
        eligibility_data: Optional[Dict[str, Any]],
        security_analysis: Dict[str, Any],
        risk_flags: List[str],
        clean_text: str
    ) -> (DecisionType, str, str):
        """
        Determines the single terminal decision under Section 3 & 4 rules.
        """
        # 1. ESCALATE Triggers: Legal threats or severe safety violations
        if security_analysis.get("is_legal_threat") or security_analysis.get("is_safety_threat"):
            return (
                "ESCALATE",
                "Customer invoked legal action, regulatory complaints, or critical safety language. Mandatory human escalation.",
                "I understand the urgency of your situation. Due to the nature of your concern, I have escalated your case directly to our Senior Management and Escalations team. A manager will contact you directly within 2 hours."
            )

        # 2. ASK Trigger: No order ID and customer has multiple candidate orders
        if not extracted_order_id:
            if len(customer_orders) > 1:
                order_list_str = " | ".join([
                    f"#{o.get('order_id')} - {o.get('items', [{}])[0].get('title', 'Item')} ({o.get('created_at', '')[:10]})"
                    for o in customer_orders[:3]
                ])
                return (
                    "ASK",
                    f"Customer did not provide an Order ID and has {len(customer_orders)} recent orders on file.",
                    f"I would be glad to help. You have multiple recent orders on file ({order_list_str}). Which order ID are you inquiring about?"
                )
            elif len(customer_orders) == 1:
                # Exactly one order, verify with customer
                single_id = customer_orders[0].get("order_id")
                return (
                    "ASK",
                    "Customer omitted Order ID, but has exactly one active order.",
                    f"Could you please confirm if your inquiry is regarding order #{single_id}?"
                )
            else:
                return (
                    "ASK",
                    "Missing order identifier and no recent orders detected in profile.",
                    "Could you please share your order number (e.g., ORD-1234) so I can look up the details?"
                )

        # 3. Order ID provided, but does not exist in DB
        if order_verification and not order_verification.get("found"):
            return (
                "ASK",
                f"Order {extracted_order_id} was not found in the database. Rule Section 4: Never invent order data.",
                f"I could not locate order #{extracted_order_id} in our records. Could you please double-check and provide the exact order number from your confirmation email?"
            )

        # 4. Order belongs to another customer (Security boundary)
        if order_verification and not order_verification.get("authorized"):
            risk_flags.append("ACCOUNT_MISMATCH_ATTEMPT")
            return (
                "ESCALATE",
                f"Order {extracted_order_id} is registered to a different account ID. Access denied.",
                f"I am unable to access details for order #{extracted_order_id} as it is associated with a different registered account. For your security, this request has been flagged for supervisor review."
            )

        # 5. Non-delivery claimed, but OTP was verified at door (Critical Claim Mismatch)
        for claim in claims_list:
            if "OTP" in (claim.discrepancy_details or ""):
                risk_flags.append("OTP_VERIFIED_CLAIM_MISMATCH")
                return (
                    "ESCALATE",
                    "CRITICAL CLAIM MISMATCH: Customer claims non-delivery, but carrier tracking confirms delivery with OTP verification. Autonomous refund strictly forbidden.",
                    f"Our courier records confirm that package #{extracted_order_id} was delivered with security code (OTP) authentication at the destination address. Because this delivery was verified via one-time passcode, I have escalated your inquiry to our Delivery Investigation Team (Reference #{extracted_order_id}-DISPUTE) to review courier telemetry."
                )

        # 6. Refund / Return Workflow Checks
        if any(i in detected_intents for i in ["refund", "return", "damaged_item"]):
            # Check 6a: Return window expired
            if eligibility_data and not eligibility_data.get("eligible"):
                if eligibility_data.get("requires_action") == "UPLOAD_PHOTO":
                    return (
                        "ASK",
                        "Policy requires photographic proof of defect/damage, but none is on file.",
                        f"Under our return policy, defective items require a photo of the issue. Could you please upload a clear photograph of the defect for order #{extracted_order_id}?"
                    )
                else:
                    return (
                        "ANSWER",
                        f"Ineligible for return: {eligibility_data.get('reason')}",
                        f"I checked the return policy for your order #{extracted_order_id}. {eligibility_data.get('reason')} As a result, this order cannot be returned or refunded."
                    )

            # Check 6b: Auto-approval threshold
            order_total = order_obj.get("total_amount", 0.0)
            auto_cap = policy_data.get("auto_approval_cap", 100.00) if policy_data else 100.00

            if order_total > auto_cap:
                risk_flags.append(f"AMOUNT_EXCEEDS_CAP (${order_total} > ${auto_cap})")
                return (
                    "ESCALATE",
                    f"Refund amount (${order_total}) exceeds autonomous approval cap (${auto_cap}). Section 4 Hard Rule: Escalate to human.",
                    f"Your return for order #{extracted_order_id} has been verified as eligible. However, because the order total (${order_total:.2f}) exceeds the autonomous agent approval limit of ${auto_cap:.2f}, I have forwarded your request to a Senior Support Specialist for immediate manual authorization."
                )

            # Check 6c: Account risk flags
            if "HIGH_REFUND_FREQUENCY_RISK" in risk_flags:
                return (
                    "ESCALATE",
                    "Account has elevated refund frequency in the past 30 days. Escalate for fraud review.",
                    f"Your request regarding order #{extracted_order_id} has been submitted to our Accounts Operations team for review. A representative will update you within 24 hours."
                )

            # Check 6d: All checks passed -> ACT
            return (
                "ACT",
                f"Eligible return for order {extracted_order_id}. Defect verified, within {policy_data.get('return_window_days')} day window, amount ${order_total} <= ${auto_cap} cap.",
                ""  # Text will be populated by execute
            )

        # 7. Address Change Workflow
        if "address_change" in detected_intents:
            status = order_obj.get("order_status")
            if status == "Processing":
                return (
                    "ACT",
                    f"Order #{extracted_order_id} is in 'Processing' state. Address modification is authorized under policy.",
                    ""
                )
            else:
                return (
                    "ANSWER",
                    f"Order #{extracted_order_id} has status '{status}'. Address cannot be modified after dispatch.",
                    f"I checked order #{extracted_order_id}. It is currently '{status}' and has already left our fulfillment facility. Therefore, the destination address cannot be changed at this stage."
                )

        # 8. Order Status Tracking
        if "order_status" in detected_intents or "general_inquiry" in detected_intents:
            delivery = order_obj.get("delivery", {})
            status = order_obj.get("order_status")
            carrier = delivery.get("carrier", "NovaCourier")
            track_num = delivery.get("tracking_number", "N/A")
            eta = delivery.get("estimated_delivery", "pending update")
            loc = delivery.get("last_location", "Transit Facility")

            resp = (
                f"Order #{extracted_order_id} ({order_obj.get('items', [{}])[0].get('title', 'Item')}) "
                f"is currently '{status}' via {carrier} (Tracking #{track_num}). "
            )
            if status == "Delivered":
                resp += f"It was delivered on {delivery.get('delivered_at')}."
            elif eta:
                resp += f"Estimated delivery is {eta} (Current location: {loc})."

            return (
                "ANSWER",
                f"Verified order tracking facts for #{extracted_order_id}. Status: {status}.",
                resp
            )

        # Default fallback
        return (
            "ANSWER",
            "General inquiry answered with verified account details.",
            f"Thank you for contacting NovaMart support. How can I assist you with order #{extracted_order_id} today?"
        )
