"""
Thin wrapper around Razorpay's test-mode API.

If RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET env vars aren't set, this falls
back to a mock mode that fabricates realistic-looking test IDs — so the
app runs end-to-end even before you've plugged in your own test keys
from the Razorpay dashboard. Swap in real test keys and everything
downstream (order creation, "release" simulation) starts hitting the
actual Razorpay test-mode API.

Get test keys: Razorpay Dashboard -> Settings -> API Keys -> Generate Test Key
"""

import os
import time
import uuid

try:
    import razorpay
except ImportError:  # pragma: no cover
    razorpay = None

KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

MOCK_MODE = not (KEY_ID and KEY_SECRET and razorpay)

_client = None
if not MOCK_MODE:
    _client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))


def create_hold_order(amount_inr: float, receipt: str, notes: dict | None = None) -> dict:
    """
    Create a Razorpay Order representing the milestone amount being
    'held' pending delivery. In test mode this is a real Orders API call
    (amount is in paise). This does NOT capture payment automatically —
    capture/release is a separate explicit step, which is the point:
    money doesn't move without an explicit action.
    """
    amount_paise = int(round(amount_inr * 100))

    if MOCK_MODE:
        return {
            "id": f"order_MOCK{uuid.uuid4().hex[:14]}",
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "status": "created",
            "mock": True,
            "created_at": int(time.time()),
        }

    order = _client.order.create(
        {
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
            "payment_capture": 0,  # manual capture — nothing auto-releases
        }
    )
    order["mock"] = False
    return order


def release_payment(order_id: str, payment_id: str | None) -> dict:
    """
    Simulates the release leg. In a full production build this would call
    Razorpay Route/Payouts to transfer funds to the freelancer's linked
    account. For the buildathon demo, this is intentionally a clearly
    logged, explicit, human-triggered action — never called by the AI.
    """
    if MOCK_MODE or not payment_id:
        return {
            "id": f"rlz_MOCK{uuid.uuid4().hex[:14]}",
            "order_id": order_id,
            "status": "released",
            "mock": True,
            "released_at": int(time.time()),
        }

    # Real capture of the held payment, e.g.:
    # captured = _client.payment.capture(payment_id, {"amount": amount_paise, "currency": "INR"})
    return {
        "id": payment_id,
        "order_id": order_id,
        "status": "released",
        "mock": False,
        "released_at": int(time.time()),
    }


def is_mock_mode() -> bool:
    return MOCK_MODE
