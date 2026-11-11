import asyncio
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.business import create_order, issue_link_code, link_identity, seed
from server.paystack_connections import (complete_paystack_setup, issue_paystack_setup_link,
    register_payment_reference)
from server.paystack_webhook import (SignatureRejected, parse_test_charge,
    verify_legacy_signature, verify_modern_signature)


WEBHOOK_SECRET = "whsec_demo_signing_secret"


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("TALLY_PUBLIC_BASE_URL", "https://tally.example")
    monkeypatch.setenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "true")
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(b"K" * 32).decode())
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", "test-v1")
    monkeypatch.setenv("TALLY_SHOP_MCP_TOKEN", "SHOP_SUPER_LONG_RANDOM_TEST_SECRET")
    monkeypatch.setenv("TALLY_DESK_MCP_TOKEN", "DESK_OTHER_LONG_RANDOM_TEST_SECRET")
    monkeypatch.setenv("TALLY_WEBHOOK_SECRET", "WEBHOOK_LONG_RANDOM_TEST_SECRET")
    seed()


async def fake_verify(_key):
    return {"permissions": ["transaction:read"], "provider_account_ref": "sandbox-account"}


def connect_admin():
    admin = link_identity(issue_link_code("staff-eni"), "desk")["session_token"]
    setup_link = issue_paystack_setup_link(admin)
    token = parse_qs(urlsplit(setup_link["setup_url"]).fragment)["token"][0]
    return asyncio.run(complete_paystack_setup(
        token, "rk_test_demo_restricted", WEBHOOK_SECRET, verifier=fake_verify
    ))


def modern_header(body, secret=WEBHOOK_SECRET, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b"." + body,
                         hashlib.sha512).hexdigest()
    return {"Paystack-Signature": f"t={timestamp},v1=whk_test:{signature}"}


def test_modern_signature_contract_and_replay_window():
    body = b'{"event":"charge.success"}'
    header = modern_header(body, timestamp=1000)["Paystack-Signature"]
    assert verify_modern_signature(body, header, [WEBHOOK_SECRET], now_epoch=1200) == "whk_test"
    with pytest.raises(SignatureRejected):
        verify_modern_signature(body, header, [WEBHOOK_SECRET], now_epoch=1301)
    with pytest.raises(SignatureRejected):
        verify_modern_signature(body + b" ", header, [WEBHOOK_SECRET], now_epoch=1200)


def test_legacy_signature_is_explicit_test_only_compatibility():
    raw = b"{}"
    key = "sk_test_demo"
    signature = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    assert verify_legacy_signature(raw, signature, key) == "legacy"
    with pytest.raises(SignatureRejected):
        verify_legacy_signature(raw, signature, "rk_test_not_a_legacy_signing_key")


def test_reject_live_charge():
    with pytest.raises(ValueError):
        parse_test_charge({"event": "charge.success", "data": {"domain": "live", "status": "success"}})


def test_business_routed_webhook_accepts_exact_charge_once():
    connection = connect_admin()
    customer = link_identity(issue_link_code("cust-ada"), "shop")["session_token"]
    order = create_order(customer, [{"product_id": "cup-choc", "quantity": 2}], "paystack-001")
    provider_reference = "ASYAN-test-reference-001"
    register_payment_reference(connection["connection_id"], "sandbox-cedar-bakes",
                               order["order_id"], provider_reference)
    event = {"event": "charge.success", "data": {"id": 5678901, "reference": provider_reference,
             "amount": order["total_minor"], "currency": "NGN", "domain": "test", "status": "success"}}
    raw = json.dumps(event, separators=(",", ":")).encode()
    path = f"/webhooks/paystack/{connection['connection_id']}"
    with TestClient(app) as client:
        assert client.post(path, content=raw, headers={"Paystack-Signature": "invalid"}).status_code == 401
        match = client.post(path, content=raw, headers=modern_header(raw))
        assert match.status_code == 200 and match.json()["match_status"] == "matched"
        duplicate = client.post(path, content=raw, headers=modern_header(raw))
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True


def test_setup_page_is_no_store_and_token_stays_in_fragment():
    with TestClient(app) as client:
        response = client.get("/integrations/paystack/setup")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
