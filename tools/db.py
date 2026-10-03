"""
NovaMart Mock Database & Source of Truth (L3 Layer)
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

# Mock Database Store
MOCK_DB: Dict[str, Any] = {
    "customers": {
        "CUST-9812": {
            "customer_id": "CUST-9812",
            "name": "Sarah Jenkins",
            "email": "sarah.j@example.com",
            "phone": "+1-555-0192",
            "trust_score": 95,
            "account_created": "2024-03-12",
            "recent_refund_count_30d": 0,
            "payment_methods": [
                {"id": "PM-4242", "type": "Visa", "last4": "4242", "is_default": True}
            ]
        },
        "CUST-3310": {
            "customer_id": "CUST-3310",
            "name": "David Miller",
            "email": "dmiller@example.com",
            "phone": "+1-555-0844",
            "trust_score": 72,
            "account_created": "2025-01-20",
            "recent_refund_count_30d": 1,
            "payment_methods": [
                {"id": "PM-1122", "type": "Mastercard", "last4": "1122", "is_default": True}
            ]
        },
        "CUST-5521": {
            "customer_id": "CUST-5521",
            "name": "Elena Rostova",
            "email": "elena.r@example.com",
            "phone": "+1-555-3391",
            "trust_score": 88,
            "account_created": "2023-11-05",
            "recent_refund_count_30d": 0,
            "payment_methods": [
                {"id": "PM-7788", "type": "Amex", "last4": "7788", "is_default": True}
            ]
        },
        "CUST-1044": {
            "customer_id": "CUST-1044",
            "name": "Marcus Vance",
            "email": "marcus.v@example.com",
            "phone": "+1-555-9012",
            "trust_score": 90,
            "account_created": "2024-06-18",
            "recent_refund_count_30d": 0,
            "payment_methods": [
                {"id": "PM-3311", "type": "Visa", "last4": "3311", "is_default": True}
            ]
        },
        "CUST-2024": {
            "customer_id": "CUST-2024",
            "name": "Priya Sharma",
            "email": "priya.s@example.com",
            "phone": "+1-555-7821",
            "trust_score": 85,
            "account_created": "2023-08-10",
            "recent_refund_count_30d": 0,
            "payment_methods": [
                {"id": "PM-9901", "type": "Visa", "last4": "9901", "is_default": True}
            ]
        },
        "CUST-7700": {
            "customer_id": "CUST-7700",
            "name": "Alex Mercer (Flagged Account)",
            "email": "alex.m@untrusted-mail.com",
            "phone": "+1-555-0000",
            "trust_score": 25,
            "account_created": "2026-09-28",
            "recent_refund_count_30d": 3,
            "payment_methods": [
                {"id": "PM-0000", "type": "PrepaidCard", "last4": "0000", "is_default": True}
            ]
        }
    },
    "orders": {
        "ORD-4491": {
            "order_id": "ORD-4491",
            "customer_id": "CUST-9812",
            "created_at": "2026-09-30T10:00:00Z",
            "order_status": "Delivered",
            "payment_status": "Captured",
            "payment_method": "Visa ending 4242",
            "total_amount": 79.99,
            "category": "Electronics",
            "items": [
                {
                    "item_id": "ITEM-HP-01",
                    "title": "NovaPulse Pro Wireless Headphones",
                    "unit_price": 79.99,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "Delivered",
                "carrier": "NovaCourier Express",
                "tracking_number": "NC-9981203",
                "delivered_at": "2026-10-02T14:30:00Z",
                "otp_required": False,
                "otp_verified": False,
                "shipping_address": {
                    "street": "742 Evergreen Terrace",
                    "city": "Springfield",
                    "state": "IL",
                    "zip": "62704"
                }
            },
            "evidence_on_file": {
                "photo_url": "https://storage.novamart.internal/evidence/ORD-4491/damaged_speaker.jpg",
                "uploaded_at": "2026-10-02T15:00:00Z",
                "verified_defect": True
            }
        },
        "ORD-9023": {
            "order_id": "ORD-9023",
            "customer_id": "CUST-3310",
            "created_at": "2026-09-29T08:15:00Z",
            "order_status": "Delivered",
            "payment_status": "Captured",
            "payment_method": "Mastercard ending 1122",
            "total_amount": 899.00,
            "category": "HighValueElectronics",
            "items": [
                {
                    "item_id": "ITEM-LT-90",
                    "title": "Titan 16 Pro Gaming Laptop",
                    "unit_price": 899.00,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "Delivered",
                "carrier": "NovaSecure Freight",
                "tracking_number": "NSF-441029",
                "delivered_at": "2026-10-03T10:15:00Z",
                "otp_required": True,
                "otp_verified": True,
                "otp_entered": "7841",
                "recipient_signature": "D. Miller",
                "delivery_lat_lon": "37.7749,-122.4194",
                "shipping_address": {
                    "street": "100 Montgomery St, Suite 400",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": "94104"
                }
            },
            "evidence_on_file": None
        },
        "ORD-1102": {
            "order_id": "ORD-1102",
            "customer_id": "CUST-5521",
            "created_at": "2026-10-02T18:00:00Z",
            "order_status": "Processing",
            "payment_status": "Captured",
            "payment_method": "Amex ending 7788",
            "total_amount": 129.50,
            "category": "HomeAndKitchen",
            "items": [
                {
                    "item_id": "ITEM-CK-11",
                    "title": "Ceramic Non-Stick Cookware Set (10-Piece)",
                    "unit_price": 129.50,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "Order Placed - Warehouse Packing",
                "carrier": "UPS Ground",
                "tracking_number": "Pending",
                "delivered_at": None,
                "otp_required": False,
                "otp_verified": False,
                "shipping_address": {
                    "street": "456 Oak Avenue, Apt 2B",
                    "city": "Chicago",
                    "state": "IL",
                    "zip": "60601"
                }
            },
            "evidence_on_file": None
        },
        "ORD-1289": {
            "order_id": "ORD-1289",
            "customer_id": "CUST-5521",
            "created_at": "2026-10-01T12:00:00Z",
            "order_status": "Shipped",
            "payment_status": "Captured",
            "payment_method": "Amex ending 7788",
            "total_amount": 49.99,
            "category": "HomeAndKitchen",
            "items": [
                {
                    "item_id": "ITEM-BL-04",
                    "title": "Stainless Steel Personal Blender",
                    "unit_price": 49.99,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "In Transit",
                "carrier": "USPS Priority",
                "tracking_number": "9400100000000000001289",
                "delivered_at": None,
                "otp_required": False,
                "otp_verified": False,
                "shipping_address": {
                    "street": "456 Oak Avenue, Apt 2B",
                    "city": "Chicago",
                    "state": "IL",
                    "zip": "60601"
                }
            },
            "evidence_on_file": None
        },
        "ORD-6721": {
            "order_id": "ORD-6721",
            "customer_id": "CUST-1044",
            "created_at": "2026-10-01T09:30:00Z",
            "order_status": "Shipped",
            "payment_status": "Captured",
            "payment_method": "Visa ending 3311",
            "total_amount": 249.00,
            "category": "Furniture",
            "items": [
                {
                    "item_id": "ITEM-CH-09",
                    "title": "Ergonomic Mesh Office Chair with Lumbar Support",
                    "unit_price": 249.00,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "In Transit",
                "carrier": "FedEx Express",
                "tracking_number": "FX-889102934",
                "delivered_at": None,
                "estimated_delivery": "2026-10-04 by 5:00 PM",
                "last_location": "Oakland Distribution Hub, CA",
                "shipping_address": {
                    "street": "1200 Market Street",
                    "city": "Seattle",
                    "state": "WA",
                    "zip": "98101"
                }
            },
            "evidence_on_file": None
        },
        "ORD-8810": {
            "order_id": "ORD-8810",
            "customer_id": "CUST-2024",
            "created_at": "2026-09-28T14:00:00Z",
            "order_status": "Delivered",
            "payment_status": "Captured",
            "payment_method": "Visa ending 9901",
            "total_amount": 650.00,
            "category": "HighValueElectronics",
            "items": [
                {
                    "item_id": "ITEM-TV-55",
                    "title": "Quantum 55-inch Ultra HD Smart TV",
                    "unit_price": 650.00,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "Delivered",
                "carrier": "NovaCourier Freight",
                "delivered_at": "2026-10-01T16:00:00Z",
                "otp_required": True,
                "otp_verified": True,
                "shipping_address": {
                    "street": "300 Pine Street",
                    "city": "Austin",
                    "state": "TX",
                    "zip": "78701"
                }
            },
            "evidence_on_file": None  # No photo on file!
        },
        "ORD-3342": {
            "order_id": "ORD-3342",
            "customer_id": "CUST-7700",
            "created_at": "2026-08-20T11:00:00Z",
            "order_status": "Delivered",
            "payment_status": "Captured",
            "payment_method": "PrepaidCard ending 0000",
            "total_amount": 29.99,
            "category": "Electronics",
            "items": [
                {
                    "item_id": "ITEM-CP-01",
                    "title": "Wireless Qi Charging Pad",
                    "unit_price": 29.99,
                    "quantity": 1,
                    "is_returnable": True
                }
            ],
            "delivery": {
                "status": "Delivered",
                "delivered_at": "2026-08-25T13:00:00Z"
            },
            "evidence_on_file": None
        }
    },
    "policies": {
        "Electronics": {
            "return_window_days": 14,
            "requires_photo": True,
            "restocking_fee_pct": 0,
            "auto_approval_cap": 100.00,
            "warranty_period_months": 12
        },
        "HighValueElectronics": {
            "return_window_days": 14,
            "requires_photo": True,
            "restocking_fee_pct": 0,
            "auto_approval_cap": 100.00,
            "otp_verified_non_delivery_action": "MANDATORY_HUMAN_ESCALATION",
            "warranty_period_months": 24
        },
        "HomeAndKitchen": {
            "return_window_days": 30,
            "requires_photo": False,
            "restocking_fee_pct": 0,
            "auto_approval_cap": 100.00
        },
        "Furniture": {
            "return_window_days": 30,
            "requires_photo": True,
            "restocking_fee_pct": 10,
            "auto_approval_cap": 100.00
        }
    },
    "tickets": {},
    "refunds": {},
    "escalations": []
}
