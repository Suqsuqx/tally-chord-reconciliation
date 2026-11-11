import json
import hashlib
import hmac
import time
import pytest
from fastapi.testclient import TestClient
from server.app import app
from server.business import BUSINESS_ID, seed, issue_link_code, link_identity, create_order
from server.paystack_webhook import SignatureRejected, verify_signature, parse_test_charge

SECRET = "whsec_demo_signing_secret"

@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("PAYSTACK_WEBHOOK_SIGNING_SECRET", SECRET)
    monkeypatch.setenv("PAYSTACK_TEST_BUSINESS_ID", BUSINESS_ID)
    monkeypatch.setenv("PAYSTACK_ENABLE_TEST_WEBHOOK", "true")
    monkeypatch.setenv("PAYSTACK_ALLOW_LEGACY_SIGNATURE", "false")
    seed()

def header(body, timestamp=None):
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(SECRET.encode(), str(timestamp).encode() + b"." + body, hashlib.sha512).hexdigest()
    return {"Paystack-Signature": f"t={timestamp},v1=whk_test:{signature}"}

def test_modern_signature_and_replay_window():
    body = b'{"event":"charge.success"}'
    assert verify_signature(body, header(body, 1000), signing_secret=SECRET, now_epoch=1200) == "v1"
    with pytest.raises(SignatureRejected):
        verify_signature(body, header(body, 1000), signing_secret=SECRET, now_epoch=1301)
    with pytest.raises(SignatureRejected):
        verify_signature(body + b" ", header(body, 1000), signing_secret=SECRET, now_epoch=1200)

def test_invalid_modern_does_not_downgrade():
    raw = b"{}"
    key = "sk_test_demo"
    legacy = hmac.new(key.encode(), raw, hashlib.sha512).hexdigest()
    with pytest.raises(SignatureRejected):
        verify_signature(raw, {"Paystack-Signature": "t=1000,v1=whk_test:" + "0"*128, "x-paystack-signature": legacy},
                         signing_secret=SECRET, legacy_secret_key=key, allow_legacy=True, now_epoch=1000)

def test_reject_live_charge():
    with pytest.raises(ValueError):
        parse_test_charge({"event": "charge.success", "data": {"domain":"live","status":"success"}})

def test_webhook_accepts_exact_charge_once():
    token = link_identity(issue_link_code("cust-ada"), "shop")["session_token"]
    order = create_order(token, [{"product_id": "cup-choc", "quantity": 2}], "paystack-001")
    event = {"event": "charge.success", "data": {"id":5678901, "reference":order["order_id"],
             "amount":order["total_minor"], "currency":"NGN", "domain":"test", "status":"success"}}
    raw = json.dumps(event, separators=(",", ":")).encode()
    with TestClient(app) as client:
        assert client.post("/webhooks/paystack", content=raw, headers={"Paystack-Signature":"invalid"}).status_code == 401
        match = client.post("/webhooks/paystack", content=raw, headers=header(raw))
        assert match.status_code == 200 and match.json()["match_status"] == "matched"
        duplicate = client.post("/webhooks/paystack", content=raw, headers=header(raw))
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True

def test_tenant_mismatch_closed(monkeypatch):
    monkeypatch.setenv("PAYSTACK_TEST_BUSINESS_ID", "a-different-business")
    with TestClient(app) as client:
        assert client.post("/webhooks/paystack", content=b"{}").status_code == 503
