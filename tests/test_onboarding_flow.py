import asyncio
import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest

import server.paystack_connections as paystack
from server.business import (BUSINESS_ID, ToolFailure, create_order, get_catalog,
    get_my_order, get_reconciliation_report, link_identity, record_payment_claim,
    seed, update_order_status, upsert_product)
from server.db import tx
from server.mcp import process


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("TALLY_PUBLIC_BASE_URL", "https://tally.example")
    monkeypatch.setenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "true")
    monkeypatch.setenv("TALLY_NOTION_CONNECTIONS_ENABLED", "false")
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(b"O" * 32).decode())
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", "test-v1")
    seed()


def register_owner(**extra):
    return link_identity(channel="desk", sender_identity="sim-owner-asyan",
                         display_name="ASYAN owner", business_name="ASYAN SHOP",
                         **extra)


def product_id(session_token, name):
    products = get_catalog(channel="desk", session_token=session_token)["products"]
    return next(product["id"] for product in products if product["name"] == name)


def test_conversational_registration_creates_empty_business():
    owner = register_owner(profile={"description": "Sandbox merchant"})
    assert owner["business_id"] != BUSINESS_ID
    assert owner["business_name"] == "ASYAN SHOP"
    assert owner["shop_slug"] == "asyan-shop"
    assert owner["shop_status"] == "onboarding"
    assert owner["registration_status"] == "created"
    assert owner["catalogue"] == {"product_count": 0}
    assert owner["identity_assurance"] == "unverified_simulator"
    assert get_catalog(channel="desk", session_token=owner["session_token"])["products"] == []

    resumed = link_identity(channel="desk", sender_identity="sim-owner-asyan",
                            business_slug="asyan-shop")
    assert resumed["business_id"] == owner["business_id"]
    assert resumed["registration_status"] == "resumed"
    assert resumed["catalogue"] == {"product_count": 0}
    with tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM businesses WHERE name='ASYAN SHOP'").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM businesses WHERE id=?", (BUSINESS_ID,)).fetchone()[0] == "Cedar Bakes (sandbox)"


def test_serialized_profile_and_policies_are_validated_and_saved():
    owner = register_owner()
    resumed = link_identity(
        channel="desk", sender_identity="sim-owner-asyan", business_slug="asyan-shop",
        profile=json.dumps({
            "description": "A neighborhood bakery",
            "phone": "08012345678",
            "pickup_address": "1 Herethere Street, Lagos",
        }),
        policies=json.dumps([
            {"question": "How do customers collect orders?",
             "answer": "Pickup is available in Lagos."},
        ]),
    )
    assert resumed["business_id"] == owner["business_id"]
    with tx() as conn:
        settings = conn.execute(
            "SELECT profile_json,policies_json FROM business_settings WHERE business_id=?",
            (owner["business_id"],),
        ).fetchone()
    assert json.loads(settings["profile_json"])["phone"] == "08012345678"
    assert json.loads(settings["policies_json"])[0]["question"] == (
        "How do customers collect orders?")


def test_serialized_structured_fields_reject_prose_without_partial_write():
    owner = register_owner()
    with pytest.raises(ToolFailure) as error:
        link_identity(
            channel="desk", sender_identity="sim-owner-asyan", business_slug="asyan-shop",
            profile="phone is 08012345678",
            policies=json.dumps([{"question": "Returns?", "answer": "Contact us."}]),
        )
    assert error.value.code == "INVALID_INPUT"
    with tx() as conn:
        settings = conn.execute(
            "SELECT profile_json,policies_json FROM business_settings WHERE business_id=?",
            (owner["business_id"],),
        ).fetchone()
    assert json.loads(settings["profile_json"]) == {}
    assert json.loads(settings["policies_json"]) == []


def test_prompt_only_registration_returns_both_secure_provider_links(monkeypatch):
    monkeypatch.setenv("TALLY_NOTION_CONNECTIONS_ENABLED", "true")
    monkeypatch.setenv("NOTION_CLIENT_ID", "notion-test-client")
    monkeypatch.setenv("NOTION_CLIENT_SECRET", "notion-test-secret")
    monkeypatch.setenv("NOTION_OAUTH_REDIRECT_URI",
                       "https://tally.example/integrations/notion/callback")
    response = process("desk", {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "link_identity", "arguments": {
            "sender_identity": "sim-owner-prompt-only", "business_name": "ASYAN SHOP",
        }},
    })
    result = json.loads(response["result"]["content"][0]["text"])
    assert result["registration_status"] == "created"
    assert result["shop_slug"] == "asyan-shop"
    assert result["catalogue"]["product_count"] == 0
    assert result["provider_setup"]["paystack"]["setup_url"].startswith(
        "https://tally.example/integrations/paystack/setup#token=")
    assert result["provider_setup"]["notion"]["setup_url"].startswith(
        "https://tally.example/integrations/notion/setup#token=")


def test_manual_bank_shop_activation_customer_order_claim_and_admin_confirmation():
    first = register_owner()
    upsert_product(first["session_token"], "Chocolate cupcake", 250000, 14, 3)
    owner = link_identity(
        channel="desk", sender_identity="sim-owner-asyan", business_slug="asyan-shop",
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP TEST",
                     "account_number": "0123456789"}, activate_shop=True,
    )
    launched = get_catalog(channel="desk", session_token=owner["session_token"])
    assert launched["onboarding"]["status"] == "active"
    assert launched["business_profile"] == {}
    assert launched["policies"] == []
    customer = link_identity(channel="shop", sender_identity="sim-customer-one",
                             display_name="Test customer", business_slug="asyan-shop")
    order = create_order(customer["session_token"],
                         [{"product_id": product_id(owner["session_token"], "Chocolate cupcake"),
                           "quantity": 1}],
                         "asyan-manual-001")
    assert order["payment"]["method"] == "manual_bank"
    claim = record_payment_claim(customer["session_token"], order["order_id"], "I paid by transfer")
    assert claim["verified"] is False
    assert get_my_order(customer["session_token"], order["order_id"])["status"] == "awaiting_payment"
    confirmed = update_order_status(owner["session_token"], order["order_id"], "confirmed",
                                    "Matched in the merchant sandbox bank statement")
    assert confirmed["provider_verified"] is False
    report = get_reconciliation_report(owner["session_token"])
    assert report["verified_matched_minor"] == 0
    assert report["merchant_confirmed_manual_minor"] == order["total_minor"]


def test_inactive_or_wrong_shop_context_is_rejected():
    owner = register_owner()
    with pytest.raises(ToolFailure) as error:
        link_identity(channel="desk", sender_identity="sim-owner-asyan",
                      business_slug="asyan-shop", activate_shop=True)
    assert error.value.code == "ONBOARDING_INCOMPLETE"
    assert owner["catalogue"]["product_count"] == 0
    with pytest.raises(ToolFailure) as error:
        link_identity(channel="shop", sender_identity="sim-customer-one", business_slug="asyan-shop")
    assert error.value.code == "SHOP_UNAVAILABLE"
    with pytest.raises(ToolFailure):
        link_identity(channel="shop", sender_identity="sim-customer-one", business_slug="another-shop")


def test_existing_customer_session_stops_when_shop_is_deactivated():
    owner = register_owner(
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP TEST",
                     "account_number": "0123456789"},
    )
    upsert_product(owner["session_token"], "Brownie box", 650000, 5, 3)
    link_identity(channel="desk", sender_identity="sim-owner-asyan",
                  business_slug="asyan-shop", activate_shop=True)
    customer = link_identity(channel="shop", sender_identity="sim-customer-one",
                             business_slug="asyan-shop")
    with tx() as conn:
        conn.execute("UPDATE business_settings SET onboarding_status='archived' WHERE business_id=?",
                     (owner["business_id"],))
    with pytest.raises(ToolFailure) as error:
        get_catalog(channel="shop", session_token=customer["session_token"])
    assert error.value.code == "SHOP_UNAVAILABLE"


async def fake_write_verify(_key):
    return {"permissions": ["transactions:write"], "provider_account_ref": "asyan-test-account"}


def test_paystack_connection_needs_only_restricted_key_and_claim_is_api_verified(monkeypatch):
    owner = register_owner()
    upsert_product(owner["session_token"], "Brownie box", 650000, 5, 2)
    setup_link = paystack.issue_paystack_setup_link(owner["session_token"])
    token = parse_qs(urlsplit(setup_link["setup_url"]).fragment)["token"][0]
    connected = asyncio.run(paystack.complete_paystack_setup(
        token, "rk_test_asyan_restricted", verifier=fake_write_verify
    ))
    assert connected["webhook_configured"] is False
    assert connected["webhook_url"] is None
    owner = link_identity(channel="desk", sender_identity="sim-owner-asyan",
                          business_slug="asyan-shop", activate_shop=True)
    customer = link_identity(channel="shop", sender_identity="sim-customer-paystack",
                             business_slug="asyan-shop")

    monkeypatch.setattr(paystack, "initialize_test_transaction",
                        lambda *_args, **_kwargs: {"method": "paystack", "status": "initialized",
                                                  "authorization_url": "https://checkout.paystack.test/demo",
                                                  "reference": "asyan-reference"})
    order = create_order(customer["session_token"],
                         [{"product_id": product_id(owner["session_token"], "Brownie box"),
                           "quantity": 1}],
                         "asyan-paystack-001", payment_email="customer@example.test")
    assert order["payment"]["status"] == "initialized"
    monkeypatch.setattr(paystack, "verify_test_transaction_for_order",
                        lambda *_args, **_kwargs: {"status": "success", "reference": "asyan-reference",
                                                  "transaction_id": 991122,
                                                  "amount_minor": order["total_minor"], "currency": "NGN"})
    claim = record_payment_claim(customer["session_token"], order["order_id"], "Paid")
    assert claim["verified"] is True
    assert claim["verification_source"] == "paystack_api"
    assert get_my_order(customer["session_token"], order["order_id"])["status"] == "confirmed"
