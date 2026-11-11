import json
import hashlib
import hmac
import pytest
from fastapi.testclient import TestClient
from server.app import app
from server.business import BUSINESS_ID, seed, issue_link_code, link_identity, create_order
from server.paystack_webhook import SignatureRejected, verify_signature, parse_test_charge

SECRET = "sk_test_demo_secret"

@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("PAYSTACK_TEST_SECRET_KEY", SECRET)
    monkeypatch.setenv("PAYSTACK_TEST_BUSINESS_ID", BUSINESS_ID)
    monkeypatch.setenv("PAYSTACK_ENABLE_TEST_WEBHOOK", "true")
    seed()

def header(body):
    signature = hmac.new(SECRET.encode(), body, hashlib.sha512).hexdigest()
    return {"X-Paystack-Signature": signature}

def test_documented_signature_uses_raw_body_and_test_secret_key():
    body = b'{"event":"charge.success"}'
    assert verify_signature(body, header(body), secret_key=SECRET) == "x-paystack-signature"
    with pytest.raises(SignatureRejected):
        verify_signature(body + b" ", header(body), secret_key=SECRET)
    with pytest.raises(SignatureRejected):
        verify_signature(body, header(body), secret_key="rk_test_restricted_is_not_the_signing_key")

def test_undocumented_signature_header_is_rejected():
    raw = b"{}"
    with pytest.raises(SignatureRejected):
        verify_signature(raw, {"Paystack-Signature": "t=1000,v1=whk_test:" + "0"*128}, secret_key=SECRET)

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
        assert client.post("/webhooks/paystack", content=raw, headers={"X-Paystack-Signature":"invalid"}).status_code == 401
        match = client.post("/webhooks/paystack", content=raw, headers=header(raw))
        assert match.status_code == 200 and match.json()["match_status"] == "matched"
        duplicate = client.post("/webhooks/paystack", content=raw, headers=header(raw))
        assert duplicate.status_code == 200 and duplicate.json()["duplicate"] is True

def test_tenant_mismatch_closed(monkeypatch):
    monkeypatch.setenv("PAYSTACK_TEST_BUSINESS_ID", "a-different-business")
    with TestClient(app) as client:
        assert client.post("/webhooks/paystack", content=b"{}").status_code == 503
