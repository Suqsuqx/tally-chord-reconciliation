"""Business-scoped Paystack setup and encrypted connection storage."""
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .business import actor_from_token, digest, new_id, now, require, require_role
from .credential_store import decrypt_credentials, encrypt_credentials
from .db import rowdict, tx


def _aad(connection_id, business_id):
    return f"tally|paystack|test|{business_id}|{connection_id}"


def issue_paystack_setup_link(session_token, ttl_minutes=10):
    require(os.getenv("TALLY_PAYSTACK_CONNECTIONS_ENABLED", "false").lower() == "true",
            "NOT_ENABLED", "Paystack connections are not enabled")
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        conn.execute("INSERT INTO provider_setup_sessions VALUES(?,?,?,?,?,NULL)",
                     (digest(token), actor["business_id"], actor["id"], "paystack", expires_at))
    base = os.getenv("TALLY_PUBLIC_BASE_URL", "").rstrip("/")
    require(base.startswith("https://"), "SERVER_CONFIG", "Secure public setup URL is unavailable")
    return {
        "setup_url": f"{base}/integrations/paystack/setup#token={quote(token)}",
        "expires_at": expires_at,
        "note": "Open this short-lived link privately. Never paste provider credentials into chat.",
    }


async def verify_restricted_key(restricted_key):
    if not isinstance(restricted_key, str) or not restricted_key.startswith("rk_test_"):
        raise ValueError("A Paystack TEST restricted key is required")
    headers = {"Authorization": "Bearer " + restricted_key, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get("https://api.paystack.co/transaction", params={"perPage": 1}, headers=headers)
        # Paystack evaluates restricted-key scope before request validation. An
        # intentionally incomplete initialize request must reach validation
        # (400/422), not authorization (403), to prove transactions:write.
        write_probe = await client.post("https://api.paystack.co/transaction/initialize",
                                        headers={**headers,"Content-Type":"application/json"}, json={})
    if response.status_code != 200 or write_probe.status_code not in (400, 422):
        raise ValueError("Paystack rejected the restricted key or required permission")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Paystack returned an invalid verification response") from exc
    if payload.get("status") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("Paystack connection verification failed")
    return {"permissions": ["transactions:write"], "provider_account_ref": None}


async def complete_paystack_setup(setup_token, restricted_key, webhook_secret=None, verifier=None):
    require(isinstance(setup_token, str) and len(setup_token) > 30,
            "INVALID_SETUP", "Setup link is invalid or expired")
    require(isinstance(restricted_key, str) and restricted_key.startswith("rk_test_"),
            "INVALID_KEY", "A Paystack TEST restricted key is required")
    if webhook_secret not in (None, ""):
        require(isinstance(webhook_secret, str) and webhook_secret.startswith("whsec_") and len(webhook_secret) > 12,
                "INVALID_WEBHOOK_SECRET", "Enter a valid Paystack webhook signing secret")
    with tx() as conn:
        pending = conn.execute("""SELECT s.*,a.active,a.role FROM provider_setup_sessions s
                                  JOIN actors a ON a.id=s.actor_id
                                  WHERE s.token_hash=? AND s.provider='paystack'""",
                               (digest(setup_token),)).fetchone()
        require(pending is not None and pending["used_at"] is None and pending["expires_at"] > now(),
                "INVALID_SETUP", "Setup link is invalid or expired")
        require(pending["active"] == 1 and pending["role"] == "admin",
                "FORBIDDEN", "Only an active Admin can connect Paystack")
    verifier = verifier or verify_restricted_key
    verification = await verifier(restricted_key)
    permissions = verification.get("permissions") if isinstance(verification, dict) else None
    require(isinstance(permissions, list) and "transactions:write" in permissions,
            "PROVIDER_REJECTED", "Paystack transactions:write permission could not be verified")
    with tx() as conn:
        setup = conn.execute("""SELECT s.*,a.active,a.role FROM provider_setup_sessions s
                                JOIN actors a ON a.id=s.actor_id
                                WHERE s.token_hash=? AND s.provider='paystack'""",
                             (digest(setup_token),)).fetchone()
        require(setup is not None and setup["used_at"] is None and setup["expires_at"] > now(),
                "INVALID_SETUP", "Setup link is invalid or expired")
        require(setup["active"] == 1 and setup["role"] == "admin",
                "FORBIDDEN", "Only an active Admin can connect Paystack")
        existing = conn.execute("""SELECT * FROM provider_connections
                                   WHERE business_id=? AND provider='paystack' AND environment='test'""",
                                (setup["business_id"],)).fetchone()
        connection_id = existing["id"] if existing else new_id("pcn")
        credentials = {"restricted_key": restricted_key}
        if webhook_secret:
            credentials["webhook_secret"] = webhook_secret
        ciphertext, version = encrypt_credentials(credentials, _aad(connection_id, setup["business_id"]))
        timestamp = now()
        if existing:
            conn.execute("""UPDATE provider_connections SET credentials_ciphertext=?,key_version=?,
                         permissions_json=?,provider_account_ref=?,status='active',verified_at=?,updated_at=?,revoked_at=NULL
                         WHERE id=?""",
                         (ciphertext, version, json.dumps(permissions), verification.get("provider_account_ref"),
                          timestamp, timestamp, connection_id))
        else:
            conn.execute("""INSERT INTO provider_connections
                         (id,business_id,provider,environment,credentials_ciphertext,key_version,permissions_json,
                          provider_account_ref,status,verified_at,created_at,updated_at,revoked_at)
                         VALUES(?,?, 'paystack','test',?,?,?,?, 'active',?,?,?,NULL)""",
                         (connection_id, setup["business_id"], ciphertext, version, json.dumps(permissions),
                          verification.get("provider_account_ref"), timestamp, timestamp, timestamp))
        conn.execute("UPDATE provider_setup_sessions SET used_at=? WHERE token_hash=?",
                     (timestamp, digest(setup_token)))
        conn.execute("""UPDATE business_settings SET payment_method='paystack',updated_at=?
                     WHERE business_id=?""",(timestamp,setup["business_id"]))
    base = os.getenv("TALLY_PUBLIC_BASE_URL", "").rstrip("/")
    return {
        "connection_id": connection_id,
        "provider": "paystack",
        "environment": "test",
        "status": "active",
        "permissions": permissions,
        "webhook_configured": bool(webhook_secret),
        "webhook_url": f"{base}/webhooks/paystack/{connection_id}" if webhook_secret else None,
    }


def load_paystack_connection_for_business(business_id):
    with tx() as conn:
        row = conn.execute("""SELECT id FROM provider_connections WHERE business_id=?
                              AND provider='paystack' AND environment='test' AND status='active'""",
                           (business_id,)).fetchone()
    return load_paystack_connection(row["id"]) if row else None


def initialize_test_transaction(business_id, order_id, amount_minor, customer_email, requester=None):
    """Create one Paystack TEST hosted checkout and persist its order mapping."""
    require(isinstance(customer_email,str) and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",customer_email.strip()),
            "INVALID_INPUT","A customer email is required for Paystack checkout")
    connection=load_paystack_connection_for_business(business_id)
    require(connection is not None,"NOT_CONNECTED","Paystack is not connected for this business")
    with tx() as conn:
        existing=conn.execute("""SELECT * FROM payment_provider_references WHERE provider='paystack'
                                 AND environment='test' AND connection_id=? AND order_id=?""",
                              (connection["id"],order_id)).fetchone()
        if existing and existing["checkout_url"]:
            return {"method":"paystack","status":existing["status"],
                    "authorization_url":existing["checkout_url"],"reference":existing["provider_reference"]}
    reference=("tly_test_"+re.sub(r"[^A-Za-z0-9_-]","",order_id))[:100]
    payload={"email":customer_email.strip(),"amount":str(amount_minor),"currency":"NGN",
             "reference":reference,"metadata":json.dumps({"tally_order_id":order_id})}
    if requester is None:
        with httpx.Client(timeout=10.0) as client:
            response=client.post("https://api.paystack.co/transaction/initialize",
                                 headers={"Authorization":"Bearer "+connection["credentials"]["restricted_key"],
                                          "Content-Type":"application/json","Accept":"application/json"},json=payload)
        if response.status_code != 200:raise ValueError("Paystack checkout could not be initialized")
        provider=response.json()
    else:
        provider=requester(payload,connection)
    data=provider.get("data") if isinstance(provider,dict) and provider.get("status") is True else None
    require(isinstance(data,dict) and isinstance(data.get("authorization_url"),str) and
            isinstance(data.get("reference"),str),"PROVIDER_REJECTED","Paystack checkout could not be initialized")
    register_payment_reference(connection["id"],business_id,order_id,data["reference"],
                               checkout_url=data["authorization_url"],access_code=data.get("access_code"))
    return {"method":"paystack","status":"initialized","authorization_url":data["authorization_url"],
            "reference":data["reference"]}


def verify_test_transaction_for_order(business_id, order_id, requester=None):
    connection=load_paystack_connection_for_business(business_id)
    if connection is None:return None
    with tx() as conn:
        mapping=conn.execute("""SELECT * FROM payment_provider_references WHERE provider='paystack'
                                AND environment='test' AND connection_id=? AND business_id=? AND order_id=?""",
                             (connection["id"],business_id,order_id)).fetchone()
    if mapping is None:return None
    reference=mapping["provider_reference"]
    if requester is None:
        with httpx.Client(timeout=10.0) as client:
            response=client.get("https://api.paystack.co/transaction/verify/"+quote(reference,safe=""),
                                headers={"Authorization":"Bearer "+connection["credentials"]["restricted_key"],
                                         "Accept":"application/json"})
        if response.status_code != 200:return {"status":"not_verified","reference":reference}
        provider=response.json()
    else:
        provider=requester(reference,connection)
    data=provider.get("data") if isinstance(provider,dict) and provider.get("status") is True else None
    if not isinstance(data,dict) or data.get("status")!="success" or data.get("domain")!="test":
        return {"status":"not_verified","reference":reference}
    return {"status":"success","reference":reference,"transaction_id":data.get("id"),
            "amount_minor":data.get("amount"),"currency":data.get("currency")}


def load_paystack_connection(connection_id):
    with tx() as conn:
        row = conn.execute("""SELECT * FROM provider_connections
                              WHERE id=? AND provider='paystack' AND environment='test' AND status='active'""",
                           (connection_id,)).fetchone()
    if row is None:
        return None
    safe = rowdict(row)
    safe["credentials"] = decrypt_credentials(
        safe.pop("credentials_ciphertext"), safe["key_version"], _aad(safe["id"], safe["business_id"])
    )
    return safe


def register_payment_reference(connection_id, business_id, order_id, provider_reference,
                               checkout_url=None, access_code=None):
    require(isinstance(provider_reference, str) and 8 <= len(provider_reference) <= 120,
            "INVALID_REFERENCE", "Provider reference is invalid")
    with tx() as conn:
        connection = conn.execute("""SELECT id FROM provider_connections
                                     WHERE id=? AND business_id=? AND provider='paystack'
                                     AND environment='test' AND status='active'""",
                                  (connection_id, business_id)).fetchone()
        require(connection is not None, "NOT_CONNECTED", "Paystack connection is unavailable")
        order = conn.execute("SELECT id FROM orders WHERE id=? AND business_id=?", (order_id, business_id)).fetchone()
        require(order is not None, "NOT_FOUND", "Order not found")
        conn.execute("""INSERT INTO payment_provider_references
                     (provider,environment,business_id,connection_id,order_id,provider_reference,created_at,
                      checkout_url,access_code,status)
                     VALUES('paystack','test',?,?,?,?,?,?,?,'initialized')
                     ON CONFLICT(provider,environment,connection_id,order_id) DO UPDATE SET
                       provider_reference=excluded.provider_reference,checkout_url=excluded.checkout_url,
                       access_code=excluded.access_code,status='initialized'""",
                     (business_id, connection_id, order_id, provider_reference, now(),checkout_url,access_code))


def resolve_payment_reference(connection_id, business_id, provider_reference):
    with tx() as conn:
        row = conn.execute("""SELECT order_id FROM payment_provider_references
                              WHERE provider='paystack' AND environment='test' AND connection_id=?
                              AND business_id=? AND provider_reference=?""",
                           (connection_id, business_id, provider_reference)).fetchone()
    return row["order_id"] if row else None
