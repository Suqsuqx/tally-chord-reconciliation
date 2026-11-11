"""Business-routed Paystack TEST webhook verification and reconciliation."""
import hashlib
import hmac
import json
import os
import re
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .business import ToolFailure, ingest_verified_payment
from .paystack_connections import load_paystack_connection, resolve_payment_reference


router = APIRouter()
HEX_SHA512 = re.compile(r"^[a-f0-9]{128}$")


class SignatureRejected(ValueError):
    pass


def verify_modern_signature(raw, header, secrets, now_epoch=None):
    """Verify Paystack-Signature using the current timestamped whsec_ contract."""
    if not isinstance(raw, bytes) or not isinstance(header, str):
        raise SignatureRejected("Malformed signature")
    stamp = None
    entries = []
    for fragment in header.split(","):
        key, separator, value = fragment.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            if stamp is not None or not value.isascii() or not value.isdigit() or len(value) > 13:
                raise SignatureRejected("Malformed timestamp")
            stamp = int(value)
        elif key == "v1":
            key_id, nested_separator, signature = value.partition(":")
            if nested_separator:
                entries.append((key_id, signature))
    if stamp is None or not entries:
        raise SignatureRejected("Malformed signature")
    current = int(time.time()) if now_epoch is None else now_epoch
    if abs(current - stamp) > 300:
        raise SignatureRejected("Expired signature")
    for secret in secrets:
        if not isinstance(secret, str) or not secret.startswith("whsec_"):
            continue
        expected = hmac.new(secret.encode(), str(stamp).encode() + b"." + raw, hashlib.sha512).hexdigest()
        for key_id, supplied in entries:
            if key_id and HEX_SHA512.fullmatch(supplied) and hmac.compare_digest(expected, supplied):
                return key_id
    raise SignatureRejected("Signature mismatch")


def verify_legacy_signature(raw, header, secret_key):
    """Explicit compatibility path for legacy X-Paystack-Signature accounts."""
    if not isinstance(secret_key, str) or not secret_key.startswith("sk_test_"):
        raise SignatureRejected("Paystack TEST secret key required")
    if not isinstance(header, str) or not HEX_SHA512.fullmatch(header):
        raise SignatureRejected("Malformed legacy signature")
    expected = hmac.new(secret_key.encode(), raw, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise SignatureRejected("Legacy signature mismatch")
    return "legacy"


def parse_test_charge(event):
    if not isinstance(event, dict):
        raise ValueError("Invalid webhook payload")
    if event.get("event") != "charge.success":
        return None
    data = event.get("data")
    if not isinstance(data, dict) or data.get("domain") != "test" or data.get("status") != "success":
        raise ValueError("Only successful test-mode charges are permitted")
    reference, amount, currency, transaction_id = (data.get(key) for key in ("reference", "amount", "currency", "id"))
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 120:
        raise ValueError("Invalid reference")
    if type(amount) is not int or amount < 1 or currency != "NGN":
        raise ValueError("Invalid amount/currency")
    if type(transaction_id) is not int or transaction_id < 1:
        raise ValueError("Invalid transaction ID")
    return {"provider_reference": reference, "transaction_id": transaction_id,
            "amount_minor": amount, "currency": "NGN"}


@router.post("/webhooks/paystack/{connection_id}")
async def webhook(connection_id: str, request: Request):
    if (os.getenv("TALLY_ENV", "sandbox") != "sandbox" or
            os.getenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "false").lower() != "true"):
        return JSONResponse({"error": "Not enabled"}, status_code=404)
    connection = load_paystack_connection(connection_id)
    if connection is None:
        return JSONResponse({"error": "Unknown connection"}, status_code=404)
    raw = await request.body()
    if not raw or len(raw) > 128 * 1024:
        return JSONResponse({"error": "Invalid request size"}, status_code=413)
    try:
        credentials = connection["credentials"]
        modern = request.headers.get("paystack-signature", "")
        if modern:
            verify_modern_signature(raw, modern, [credentials.get("webhook_secret", "")])
        else:
            verify_legacy_signature(raw, request.headers.get("x-paystack-signature", ""),
                                    credentials.get("legacy_secret_key", ""))
    except SignatureRejected:
        return JSONResponse({"error": "Unauthorized webhook"}, status_code=401)
    try:
        event = parse_test_charge(json.loads(raw))
        if event is None:
            return JSONResponse({"status": "ignored"})
        order_id = resolve_payment_reference(
            connection_id, connection["business_id"], event["provider_reference"]
        )
        if order_id is None:
            return JSONResponse({"status": "unmatched_reference"}, status_code=202)
        result = ingest_verified_payment({
            "event_id": f"paystack-test:{connection_id}:{event['transaction_id']}",
            "reference": order_id,
            "amount_minor": event["amount_minor"],
            "currency": event["currency"],
            "event_status": "success",
        }, business_id=connection["business_id"])
        return JSONResponse({"status": "processed", "match_status": result["match_status"],
                             "duplicate": result["duplicate"]})
    except (ValueError, ToolFailure):
        return JSONResponse({"error": "Invalid test transaction"}, status_code=400)
