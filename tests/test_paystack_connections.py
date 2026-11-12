import asyncio
import base64
from urllib.parse import parse_qs, urlsplit

import pytest

from server.business import ToolFailure, issue_link_code, link_identity, seed
from server.db import tx
from server.paystack_connections import (complete_paystack_setup, issue_paystack_setup_link,
    load_paystack_connection)


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("TALLY_PUBLIC_BASE_URL", "https://tally.example")
    monkeypatch.setenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "true")
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(b"E" * 32).decode())
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", "test-v1")
    seed()


async def fake_verify(_key):
    return {"permissions": ["transactions:write"], "provider_account_ref": "verified-test-account"}


def setup_token(actor_id):
    session = link_identity(issue_link_code(actor_id), "desk")["session_token"]
    link = issue_paystack_setup_link(session)
    assert "#token=" in link["setup_url"]
    return parse_qs(urlsplit(link["setup_url"]).fragment)["token"][0]


def test_credentials_are_encrypted_per_business_and_setup_is_single_use():
    token = setup_token("staff-eni")
    result = asyncio.run(complete_paystack_setup(
        token, "rk_test_business_one", "whsec_business_one", verifier=fake_verify
    ))
    loaded = load_paystack_connection(result["connection_id"])
    assert loaded["business_id"] == "sandbox-cedar-bakes"
    assert loaded["credentials"]["restricted_key"] == "rk_test_business_one"
    assert loaded["credentials"]["webhook_secret"] == "whsec_business_one"
    with tx() as conn:
        stored = conn.execute("SELECT credentials_ciphertext FROM provider_connections").fetchone()[0]
    assert "rk_test_business_one" not in stored
    assert "whsec_business_one" not in stored
    with pytest.raises(ToolFailure):
        asyncio.run(complete_paystack_setup(
            token, "rk_test_business_one", "whsec_business_one", verifier=fake_verify
        ))


def test_two_businesses_get_distinct_connection_records():
    with tx() as conn:
        conn.execute("INSERT INTO businesses VALUES('business-two','Second Shop','NGN')")
        conn.execute("""INSERT INTO actors (id,business_id,kind,role,display_name)
                      VALUES('staff-two','business-two','staff','admin','Second Owner')""")
    first = asyncio.run(complete_paystack_setup(
        setup_token("staff-eni"), "rk_test_business_one", "whsec_business_one", verifier=fake_verify
    ))
    second = asyncio.run(complete_paystack_setup(
        setup_token("staff-two"), "rk_test_business_two", "whsec_business_two", verifier=fake_verify
    ))
    assert first["connection_id"] != second["connection_id"]
    assert load_paystack_connection(first["connection_id"])["business_id"] == "sandbox-cedar-bakes"
    assert load_paystack_connection(second["connection_id"])["business_id"] == "business-two"


def test_invalid_setup_token_is_rejected_before_provider_request():
    called = False

    async def should_not_run(_key):
        nonlocal called
        called = True
        return {"permissions": ["transactions:write"]}

    with pytest.raises(ToolFailure):
        asyncio.run(complete_paystack_setup(
            "invalid-token-that-is-long-enough-to-parse",
            "rk_test_business_one", "whsec_business_one", verifier=should_not_run
        ))
    assert called is False
