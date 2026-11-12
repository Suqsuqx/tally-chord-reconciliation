import asyncio
import base64
from urllib.parse import parse_qs, urlsplit

import pytest

import server.paystack_connections as paystack
from server.business import (BUSINESS_ID, ToolFailure, create_order, get_catalog,
    get_my_order, get_reconciliation_report, link_identity, record_payment_claim,
    seed, update_order_status)
from server.db import tx


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
                         business_slug="asyan-shop", **extra)


def test_conversational_registration_reuses_placeholder_and_preserves_catalogue():
    owner = register_owner(profile={"description": "Sandbox merchant"})
    assert owner["business_id"] == BUSINESS_ID
    assert owner["business_name"] == "ASYAN SHOP"
    assert owner["shop_status"] == "onboarding"
    assert owner["identity_assurance"] == "unverified_simulator"
    assert len(get_catalog(channel="desk", session_token=owner["session_token"])["products"]) == 3

    resumed = link_identity(channel="desk", sender_identity="sim-owner-asyan",
                            business_slug="asyan-shop")
    assert resumed["business_id"] == owner["business_id"]
    with tx() as conn:
        assert conn.execute("SELECT COUNT(*) FROM businesses WHERE name='ASYAN SHOP'").fetchone()[0] == 1


def test_manual_bank_shop_activation_customer_order_claim_and_admin_confirmation():
    register_owner()
    owner = link_identity(
        channel="desk", sender_identity="sim-owner-asyan", business_slug="asyan-shop",
        manual_bank={"bank_name": "Sandbox Bank", "account_name": "ASYAN SHOP TEST",
                     "account_number": "0123456789"}, activate_shop=True,
    )
    customer = link_identity(channel="shop", sender_identity="sim-customer-one",
                             display_name="Test customer", business_slug="asyan-shop")
    order = create_order(customer["session_token"], [{"product_id": "cup-choc", "quantity": 1}],
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
    register_owner()
    with pytest.raises(ToolFailure) as error:
        link_identity(channel="shop", sender_identity="sim-customer-one", business_slug="asyan-shop")
    assert error.value.code == "SHOP_UNAVAILABLE"
    with pytest.raises(ToolFailure):
        link_identity(channel="shop", sender_identity="sim-customer-one", business_slug="another-shop")


async def fake_write_verify(_key):
    return {"permissions": ["transactions:write"], "provider_account_ref": "asyan-test-account"}


def test_paystack_connection_needs_only_restricted_key_and_claim_is_api_verified(monkeypatch):
    owner = register_owner()
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
    order = create_order(customer["session_token"], [{"product_id": "brownie", "quantity": 1}],
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
