"""Sandbox-only Paystack webhook verifier. Disabled unless explicitly configured.

WARNING: This adapter remains single-tenant until business routing is migrated.
The signed test charge is reconciled through the existing Tally ledger.
"""
import os
import json
import hmac
import hashlib
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .business import BUSINESS_ID, ToolFailure, ingest_verified_payment

router = APIRouter()
HEX_SHA512 = re.compile(r"^[a-f0-9]{128}$")

class SignatureRejected(ValueError):
    pass

def verify_signature(raw, headers, *, secret_key):
    """Verify Paystack's documented X-Paystack-Signature over the raw body."""
    h = {str(k).lower(): str(v) for k, v in headers.items()}
    if not secret_key.startswith("sk_test_"):
        raise SignatureRejected("Paystack test secret key required")
    supplied = h.get("x-paystack-signature", "")
    if not HEX_SHA512.fullmatch(supplied):
        raise SignatureRejected("Malformed signature")
    expected = hmac.new(secret_key.encode(), raw, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise SignatureRejected("Signature mismatch")
    return "x-paystack-signature"

def parse_test_charge(event):
    if not isinstance(event, dict):
        raise ValueError("Invalid webhook payload")
    if event.get("event") != "charge.success":
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("domain") != "test" or data.get("status") != "success":
        raise ValueError("Only successful test-mode charges are permitted")
    reference, amount, currency, txn_id = (data.get(key) for key in ("reference", "amount", "currency", "id"))
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 120:
        raise ValueError("Invalid reference")
    if type(amount) is not int or amount < 1 or currency != "NGN":
        raise ValueError("Invalid amount/currency")
    if type(txn_id) is not int or txn_id < 1:
        raise ValueError("Invalid transaction ID")
    return {"event_id": f"paystack-test-{txn_id}", "reference": reference,
            "amount_minor": amount, "currency": "NGN", "event_status": "success"}

@router.post("/webhooks/paystack")
async def webhook(request: Request):
    if os.getenv("TALLY_ENV", "sandbox") != "sandbox" or os.getenv("PAYSTACK_ENABLE_TEST_WEBHOOK", "false").lower() != "true":
        return JSONResponse({"error": "Not enabled"}, status_code=404)
    if os.getenv("PAYSTACK_TEST_BUSINESS_ID", "") != BUSINESS_ID:
        return JSONResponse({"error": "Merchant mapping not configured"}, status_code=503)
    raw = await request.body()
    if not raw or len(raw) > 128 * 1024:
        return JSONResponse({"error": "Invalid request size"}, status_code=413)
    try:
        verify_signature(raw, request.headers, secret_key=os.getenv("PAYSTACK_TEST_SECRET_KEY", ""))
    except SignatureRejected:
        return JSONResponse({"error": "Unauthorized webhook"}, status_code=401)
    try:
        event = parse_test_charge(json.loads(raw))
        if event is None:
            return JSONResponse({"status": "ignored"})
        result = ingest_verified_payment(event)
        return JSONResponse({"status": "processed", "match_status": result["match_status"], "duplicate": result["duplicate"]})
    except (ValueError, ToolFailure):
        return JSONResponse({"error": "Invalid test transaction"}, status_code=400)
