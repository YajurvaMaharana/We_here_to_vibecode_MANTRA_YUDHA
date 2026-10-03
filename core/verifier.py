"""
NovaMart Sentinel-Governor Claim Verification Engine (Truth vs Claim Matrix)
Cross-references untrusted L4 statements against verified L3 Database Records.
"""

from typing import Dict, Any, List, Optional
from core.models import ClaimVerification, ClaimStatus


class ClaimVerifier:
    @staticmethod
    def verify_order_claim(customer_id: str, order_id: Optional[str], order_data_res: Dict[str, Any], raw_message: str) -> List[ClaimVerification]:
        claims: List[ClaimVerification] = []

        if not order_id:
            claims.append(ClaimVerification(
                claim_text="Order reference implied in message",
                database_truth="No Order ID supplied by customer",
                status="UNVERIFIED",
                discrepancy_details="Customer did not specify an Order ID."
            ))
            return claims

        if not order_data_res.get("found"):
            claims.append(ClaimVerification(
                claim_text=f"Claims purchase of order {order_id}",
                database_truth=f"Order {order_id} does not exist in NovaMart database",
                status="CLAIM_MISMATCH",
                discrepancy_details="Order ID not found in database."
            ))
            return claims

        if not order_data_res.get("authorized"):
            claims.append(ClaimVerification(
                claim_text=f"Claims ownership of order {order_id}",
                database_truth=f"Order {order_id} belongs to a different customer ID",
                status="CLAIM_MISMATCH",
                discrepancy_details="Account ID mismatch: Order owner does not match authenticated customer."
            ))
            return claims

        order = order_data_res["order"]
        delivery = order.get("delivery", {})
        order_status = order.get("order_status")

        # 1. Non-delivery claim vs OTP delivery proof
        is_claiming_non_delivery = any(w in raw_message.lower() for w in [
            "never got", "didn't receive", "not received", "where is", "haven't received", "never arrived", "did not arrive"
        ])
        
        if is_claiming_non_delivery:
            if order_status == "Delivered":
                if delivery.get("otp_verified"):
                    claims.append(ClaimVerification(
                        claim_text="Customer claims package was never received / not delivered",
                        database_truth=f"Delivered at {delivery.get('delivered_at')} with OTP authentication (Code verified at door).",
                        status="CLAIM_MISMATCH",
                        discrepancy_details="CRITICAL FRAUD / DISPUTE FLAG: Delivery was completed with secure OTP verification, contradicting customer claim."
                    ))
                else:
                    claims.append(ClaimVerification(
                        claim_text="Customer claims package was never received",
                        database_truth=f"Status is Delivered at {delivery.get('delivered_at')} (Standard carrier drop-off).",
                        status="CLAIM_MISMATCH",
                        discrepancy_details="Package marked delivered without OTP. Potential porch theft or carrier misplacement."
                    ))
            elif order_status in ["Shipped", "Processing"]:
                claims.append(ClaimVerification(
                    claim_text="Customer inquires about pending delivery",
                    database_truth=f"Order is currently '{order_status}' with {delivery.get('carrier', 'carrier')}.",
                    status="VERIFIED_MATCH",
                    discrepancy_details=None
                ))

        # 2. Damage or Defect Claim
        is_claiming_damage = any(w in raw_message.lower() for w in [
            "damaged", "defect", "distorted", "broken", "cracked", "faulty", "scratch"
        ])
        if is_claiming_damage:
            evidence = order.get("evidence_on_file")
            if evidence and evidence.get("photo_url"):
                claims.append(ClaimVerification(
                    claim_text="Customer claims item is damaged or defective",
                    database_truth=f"Defect photo verified on file: {evidence.get('photo_url')}",
                    status="VERIFIED_MATCH",
                    discrepancy_details=None
                ))
            else:
                claims.append(ClaimVerification(
                    claim_text="Customer claims item is damaged or defective",
                    database_truth="No photo evidence or inspection report found in customer ticket/order records.",
                    status="REQUIRES_EVIDENCE",
                    discrepancy_details="Missing photographic evidence required by return policy."
                ))

        # 3. Ownership and Status Claim
        claims.append(ClaimVerification(
            claim_text=f"Customer is authorized purchaser of {order_id}",
            database_truth=f"Customer ID {customer_id} matches verified database record.",
            status="VERIFIED_MATCH",
            discrepancy_details=None
        ))

        return claims
