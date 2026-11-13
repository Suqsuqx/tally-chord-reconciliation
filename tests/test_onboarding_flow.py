import asyncio
import base64
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

import server.paystack_connections as paystack
from server.app import app
from server.business import (ToolFailure, create_order, get_catalog,
    get_my_order, get_reconciliation_report, issue_link_code, link_identity, record_payment_claim,
    update_order_status, upsert_product)
from server.db import tx
from server.mcp import process
from tests.demo_seed import DEMO_BUSINESS_ID,seed_demo


@pytest.fixture(autouse=True)
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TALLY_DB_PATH", str(tmp_path / "tally.db"))
    monkeypatch.setenv("TALLY_ENV", "sandbox")
    monkeypatch.setenv("TALLY_PUBLIC_BASE_URL", "https://tally.example")
    monkeypatch.setenv("TALLY_SHOP_BOUND_SLUG", "asyan-shop")
    monkeypatch.setenv("TALLY_SHOP_AGENT_URL", "https://chat.example/asyan-agent")
    monkeypatch.setenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "true")
    monkeypatch.setenv("TALLY_NOTION_CONNECTIONS_ENABLED", "false")
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY",
                       base64.urlsafe_b64encode(b"O" * 32).decode())
    monkeypatch.setenv("TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION", "test-v1")
    seed_demo()


def register_owner(**extra):
    return link_identity(channel="desk", sender_identity="sim-owner-asyan",
                         display_name="ASYAN owner", business_name="ASYAN SHOP",
                         **extra)


def product_id(session_token, name):
    products = get_catalog(channel="desk", session_token=session_token)["products"]
    return next(product["id"] for product in products if product["name"] == name)


def test_conversational_registration_creates_empty_business():
    owner = register_owner(profile={"description": "Sandbox merchant"})
    assert owner["business_id"] != DEMO_BUSINESS_ID
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
        assert conn.execute("SELECT name FROM businesses WHERE id=?", (DEMO_BUSINESS_ID,)).fetchone()[0] == "Test Merchant Fixture"


def test_unscripted_business_name_is_preserved_and_slugged():
    owner = link_identity(
        channel="desk", sender_identity="sim-owner-kora", display_name="Kora owner",
        business_name="Kora Books and Gifts",
    )
    assert owner["business_name"] == "Kora Books and Gifts"
    assert owner["shop_slug"] == "kora-books-and-gifts"
    assert owner["shop_status"] == "onboarding"
    assert owner["catalogue"] == {"product_count": 0}


def test_other_merchant_cannot_activate_through_existing_shop_agent():
    owner = link_identity(
        channel="desk", sender_identity="sim-owner-kora", display_name="Kora owner",
        business_name="Kora Books and Gifts",
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "Kora Books and Gifts",
                     "account_number": "0123456789"},
    )
    upsert_product(owner["session_token"], "Notebook", 350000, 8, 2)
    with pytest.raises(ToolFailure) as error:
        link_identity(channel="desk", sender_identity="sim-owner-kora",
                      business_slug="kora-books-and-gifts", activate_shop=True)
    assert error.value.code == "SHOP_CHANNEL_UNAVAILABLE"


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


def test_current_desk_session_saves_approved_profile_and_policies():
    owner = register_owner()
    response = process("desk", {
        "jsonrpc": "2.0", "id": 91, "method": "tools/call",
        "params": {"name": "link_identity", "arguments": {
            "session_token": owner["session_token"],
            "profile": {
                "category": "Bakery and snacks",
                "phone": "08012345678",
                "pickup_address": "1 Herethere, Lagos",
            },
            "policies": [
                {"question": "How are orders fulfilled?", "answer": "Pickup only."},
            ],
        }},
    })
    result = json.loads(response["result"]["content"][0]["text"])
    assert response["result"].get("isError") is not True
    assert result["business_id"] == owner["business_id"]
    saved = get_catalog(channel="desk", session_token=result["session_token"])
    assert saved["business_profile"]["phone"] == "08012345678"
    assert saved["policies"] == [
        {"question": "How are orders fulfilled?", "answer": "Pickup only."},
    ]


def test_session_onboarding_update_rejects_identity_mixing_and_operator_write():
    owner = register_owner()
    with pytest.raises(ToolFailure) as error:
        link_identity(
            channel="desk", session_token=owner["session_token"],
            sender_identity="sim-owner-asyan", profile={"phone": "08012345678"},
        )
    assert error.value.code == "INVALID_INPUT"

    operator = link_identity(issue_link_code("staff-tola"), "desk")
    with pytest.raises(ToolFailure) as error:
        link_identity(
            channel="desk", session_token=operator["session_token"],
            policies=[{"question": "Returns?", "answer": "Contact the owner."}],
        )
    assert error.value.code == "FORBIDDEN"


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
    assert owner["shop_access"] == {
        "status": "active", "shop_slug": "asyan-shop",
        "entry_url": "https://tally.example/shop/asyan-shop",
    }
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


def test_bound_shop_mcp_injects_one_business_and_rejects_store_switch(monkeypatch):
    owner = register_owner(
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP TEST",
                     "account_number": "0123456789"},
    )
    upsert_product(owner["session_token"], "Brownie box", 650000, 5, 3)
    link_identity(channel="desk", sender_identity="sim-owner-asyan",
                  business_slug="asyan-shop", activate_shop=True)
    monkeypatch.setenv("TALLY_SHOP_BOUND_SLUG", "asyan-shop")

    linked_response = process("shop", {
        "jsonrpc": "2.0", "id": 21, "method": "tools/call",
        "params": {"name": "link_identity", "arguments": {
            "sender_identity": "sim-bound-customer",
        }},
    })
    linked = json.loads(linked_response["result"]["content"][0]["text"])
    assert linked["business_name"] == "ASYAN SHOP"
    assert linked["shop_slug"] == "asyan-shop"

    catalog_response = process("shop", {
        "jsonrpc": "2.0", "id": 22, "method": "tools/call",
        "params": {"name": "get_catalog", "arguments": {}},
    })
    catalog = json.loads(catalog_response["result"]["content"][0]["text"])
    assert catalog["business"] == "ASYAN SHOP"

    mismatch_response = process("shop", {
        "jsonrpc": "2.0", "id": 23, "method": "tools/call",
        "params": {"name": "link_identity", "arguments": {
            "sender_identity": "sim-store-switch", "business_slug": "another-shop",
        }},
    })
    mismatch = json.loads(mismatch_response["result"]["content"][0]["text"])
    assert mismatch_response["result"]["isError"] is True
    assert mismatch["error"] == "SHOP_CONTEXT_MISMATCH"


def test_shop_remembers_customer_name_and_exposes_it_on_merchant_orders():
    owner = register_owner(
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP",
                     "account_number": "0123456789"},
    )
    upsert_product(owner["session_token"], "Brownie box", 650000, 5, 2)
    owner = link_identity(channel="desk", sender_identity="sim-owner-asyan",
                          business_slug="asyan-shop", activate_shop=True)
    first = link_identity(channel="shop", sender_identity="sim-remembered-customer",
                          business_slug="asyan-shop")
    assert first["customer_profile"] == {
        "display_name": None, "name_on_file": False, "payment_email_on_file": False,
    }
    named = link_identity(channel="shop", sender_identity="sim-remembered-customer",
                          display_name="Momo A.", business_slug="asyan-shop")
    assert named["customer_profile"]["display_name"] == "Momo A."
    resumed = link_identity(channel="shop", sender_identity="sim-remembered-customer",
                            business_slug="asyan-shop")
    assert resumed["customer_profile"]["name_on_file"] is True
    order = create_order(
        resumed["session_token"],
        [{"product_id": product_id(owner["session_token"], "Brownie box"), "quantity": 1}],
        "remembered-name-order",
    )
    from server.business import get_order_queue
    queued = get_order_queue(owner["session_token"])["orders"]
    assert next(item for item in queued if item["id"] == order["order_id"])["customer_name"] == "Momo A."


def test_shop_entry_redirect_exists_only_after_bound_business_activation(monkeypatch):
    monkeypatch.setenv("TALLY_SHOP_BOUND_SLUG", "asyan-shop")
    monkeypatch.setenv("TALLY_SHOP_AGENT_URL", "https://chat.example/asyan-agent")
    with TestClient(app) as client:
        assert client.get("/shop/asyan-shop", follow_redirects=False).status_code == 404
    owner = register_owner(
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP TEST",
                     "account_number": "0123456789"},
    )
    upsert_product(owner["session_token"], "Brownie box", 650000, 5, 3)
    link_identity(channel="desk", sender_identity="sim-owner-asyan",
                  business_slug="asyan-shop", activate_shop=True)
    with TestClient(app) as client:
        response = client.get("/shop/asyan-shop", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == "https://chat.example/asyan-agent"
        assert client.get("/shop/another-shop", follow_redirects=False).status_code == 404


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
                             display_name="Momo", customer_email="customer@example.test",
                             business_slug="asyan-shop")

    checkout = {}
    def initialize(_business_id, _order_id, _amount_minor, email):
        checkout["email"] = email
        paystack.register_payment_reference(
            connected["connection_id"], _business_id, _order_id, "asyan-reference",
            checkout_url="https://checkout.paystack.test/demo",
        )
        return {"method": "paystack", "status": "initialized",
                "authorization_url": "https://checkout.paystack.test/demo",
                "reference": "asyan-reference"}
    monkeypatch.setattr(paystack, "initialize_test_transaction", initialize)
    order = create_order(customer["session_token"],
                         [{"product_id": product_id(owner["session_token"], "Brownie box"),
                           "quantity": 1}],
                         "asyan-paystack-001")
    assert order["payment"]["status"] == "initialized"
    assert order["payment"]["customer_action"] == {
        "type": "open_checkout",
        "label": "Pay securely with Paystack",
        "url": "https://checkout.paystack.test/demo",
    }
    assert checkout["email"] == "customer@example.test"
    monkeypatch.setattr(paystack, "verify_test_transaction_for_order",
                        lambda *_args, **_kwargs: {"status": "not_verified",
                                                  "reference": "asyan-reference"})
    awaiting = get_my_order(customer["session_token"], order["order_id"])
    assert awaiting["status"] == "awaiting_payment"
    assert awaiting["payment"]["customer_action"]["url"] == "https://checkout.paystack.test/demo"
    monkeypatch.setattr(paystack, "verify_test_transaction_for_order",
                        lambda *_args, **_kwargs: {"status": "success", "reference": "asyan-reference",
                                                  "transaction_id": 991122,
                                                  "amount_minor": order["total_minor"], "currency": "NGN"})
    confirmed = get_my_order(customer["session_token"], order["order_id"])
    assert confirmed["status"] == "confirmed"
    assert confirmed["payment"] == {
        "method": "paystack", "status": "verified", "verified": True,
        "verification_source": "paystack_api",
    }
    with tx() as conn:
        assert conn.execute(
            "SELECT status FROM payment_provider_references WHERE order_id=?",
            (order["order_id"],),
        ).fetchone()[0] == "verified"
    duplicate_claim = record_payment_claim(
        customer["session_token"], order["order_id"], "Paid",
    )
    assert duplicate_claim["verified"] is True
    assert duplicate_claim["verification_source"] == "paystack_api"
