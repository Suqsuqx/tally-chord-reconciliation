"""Business-scoped Notion OAuth and bounded, read-only content previews."""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from .business import actor_from_token, digest, new_id, now, require, require_role
from .credential_store import decrypt_credentials, encrypt_credentials
from .db import rowdict, tx


NOTION_API_ROOT = "https://api.notion.com/v1"
MAX_DISCOVERY_ITEMS = 50
MAX_PREVIEW_BLOCKS = 100
MAX_PREVIEW_ROWS = 50
MAX_TEXT_CHARS = 500


def _aad(connection_id, business_id):
    return f"tally|notion|oauth|{business_id}|{connection_id}"


def _enabled():
    require(os.getenv("TALLY_NOTION_CONNECTIONS_ENABLED", "false").lower() == "true",
            "NOT_ENABLED", "Notion connections are not enabled")


def _oauth_config():
    client_id = os.getenv("NOTION_CLIENT_ID", "").strip()
    client_secret = os.getenv("NOTION_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("NOTION_OAUTH_REDIRECT_URI", "").strip()
    require(client_id and client_secret, "SERVER_CONFIG", "Notion OAuth is unavailable")
    require(redirect_uri.startswith("https://"), "SERVER_CONFIG", "Secure Notion redirect is unavailable")
    return client_id, client_secret, redirect_uri


def issue_notion_setup_link(session_token, ttl_minutes=10):
    """Create a one-time private setup link for an authenticated business Admin."""
    _enabled()
    _oauth_config()
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
        token = secrets.token_urlsafe(32)
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        conn.execute("INSERT INTO provider_setup_sessions VALUES(?,?,?,?,?,NULL)",
                     (digest(token), actor["business_id"], actor["id"], "notion", expires_at))
    base = os.getenv("TALLY_PUBLIC_BASE_URL", "").rstrip("/")
    require(base.startswith("https://"), "SERVER_CONFIG", "Secure public setup URL is unavailable")
    return {
        "setup_url": f"{base}/integrations/notion/setup#token={token}",
        "expires_at": expires_at,
        "note": "Open this short-lived link privately and choose only the business pages Tally may read.",
    }


def start_notion_oauth(setup_token, ttl_minutes=10):
    """Consume a setup token and create a one-time OAuth state value."""
    _enabled()
    client_id, _client_secret, redirect_uri = _oauth_config()
    require(isinstance(setup_token, str) and len(setup_token) > 30,
            "INVALID_SETUP", "Setup link is invalid or expired")
    state = secrets.token_urlsafe(32)
    timestamp = now()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
    with tx() as conn:
        setup = conn.execute("""SELECT s.*,a.active,a.role FROM provider_setup_sessions s
                                JOIN actors a ON a.id=s.actor_id
                                WHERE s.token_hash=? AND s.provider='notion'""",
                             (digest(setup_token),)).fetchone()
        require(setup is not None and setup["used_at"] is None and setup["expires_at"] > timestamp,
                "INVALID_SETUP", "Setup link is invalid or expired")
        require(setup["active"] == 1 and setup["role"] == "admin",
                "FORBIDDEN", "Only an active Admin can connect Notion")
        conn.execute("""INSERT INTO provider_oauth_states
                     (state_hash,business_id,actor_id,provider,expires_at,used_at,created_at)
                     VALUES(?,?,?,?,?,NULL,?)""",
                     (digest(state), setup["business_id"], setup["actor_id"], "notion", expires_at, timestamp))
        conn.execute("UPDATE provider_setup_sessions SET used_at=? WHERE token_hash=?",
                     (timestamp, digest(setup_token)))
    authorize_url = NOTION_API_ROOT + "/oauth/authorize?" + urlencode({
        "owner": "user",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    })
    return {"authorize_url": authorize_url, "expires_at": expires_at}


def cancel_notion_oauth(state):
    """Consume a denied OAuth state without revealing whether it existed."""
    if not isinstance(state, str) or len(state) <= 30:
        return
    with tx() as conn:
        conn.execute("""UPDATE provider_oauth_states SET used_at=?
                     WHERE state_hash=? AND provider='notion' AND used_at IS NULL""",
                     (now(), digest(state)))


async def exchange_notion_code(code):
    client_id, client_secret, redirect_uri = _oauth_config()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            NOTION_API_ROOT + "/oauth/token",
            auth=(client_id, client_secret),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        )
    if response.status_code != 200:
        raise ValueError("Notion authorization could not be completed")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Notion returned an invalid authorization response") from exc
    return payload


async def exchange_notion_refresh_token(refresh_token):
    client_id, client_secret, _redirect_uri = _oauth_config()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            NOTION_API_ROOT + "/oauth/token",
            auth=(client_id, client_secret),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"grant_type": "refresh_token", "refresh_token": refresh_token},
        )
    if response.status_code != 200:
        raise ValueError("Notion authorization could not be refreshed")
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Notion returned an invalid refresh response") from exc


def _headers(access_token):
    return {
        "Authorization": "Bearer " + access_token,
        "Notion-Version": os.getenv("NOTION_API_VERSION", "2026-03-11"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _plain_text(rich_text):
    if not isinstance(rich_text, list):
        return ""
    return "".join(str(item.get("plain_text", "")) for item in rich_text if isinstance(item, dict))[:MAX_TEXT_CHARS]


def _title(item):
    if not isinstance(item, dict):
        return "Untitled"
    if item.get("object") == "data_source":
        value = _plain_text(item.get("title"))
        return value or "Untitled data source"
    properties = item.get("properties")
    if isinstance(properties, dict):
        for prop in properties.values():
            if isinstance(prop, dict) and prop.get("type") == "title":
                value = _plain_text(prop.get("title"))
                if value:
                    return value
    return "Untitled page"


def _resource_summary(item):
    return {
        "id": str(item.get("id", ""))[:80],
        "type": item.get("object") if item.get("object") in ("page", "data_source") else "unknown",
        "title": _title(item),
        "last_edited_time": str(item.get("last_edited_time", ""))[:40] or None,
    }


async def discover_authorized_resources(access_token, requester=None):
    """List authorized resources and probe a bounded subset for real read access."""
    if requester is not None:
        payload = await requester("POST", "/search", {"page_size": MAX_DISCOVERY_ITEMS})
    else:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                NOTION_API_ROOT + "/search",
                headers=_headers(access_token),
                json={"page_size": MAX_DISCOVERY_ITEMS},
            )
        if response.status_code != 200:
            raise ValueError("Notion authorized content could not be read")
        payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Notion returned an invalid content response")
    summaries = [_resource_summary(item) for item in results[:MAX_DISCOVERY_ITEMS]
                 if isinstance(item, dict) and item.get("object") in ("page", "data_source")]
    if requester is None:
        by_id = {item.get("id"): item for item in results if isinstance(item, dict)}
        async with httpx.AsyncClient(timeout=5.0) as client:
            for summary in summaries[:5]:
                item = by_id.get(summary["id"], {})
                try:
                    if item.get("object") == "page":
                        response = await client.get(
                            NOTION_API_ROOT + f"/blocks/{summary['id']}/children",
                            headers=_headers(access_token), params={"page_size": 1},
                        )
                    else:
                        response = await client.post(
                            NOTION_API_ROOT + f"/data_sources/{summary['id']}/query",
                            headers=_headers(access_token), json={"page_size": 1},
                        )
                    summary["read_status"] = "readable" if response.status_code == 200 else "unreadable"
                except httpx.HTTPError:
                    summary["read_status"] = "unreadable"
    return {"resources": summaries, "truncated": bool(payload.get("has_more"))}


async def complete_notion_oauth(code, state, exchanger=None, discoverer=None):
    """Exchange a one-time code, prove content access, then encrypt the token pair."""
    _enabled()
    require(isinstance(code, str) and 8 <= len(code) <= 500,
            "INVALID_OAUTH", "Notion authorization could not be completed")
    require(isinstance(state, str) and len(state) > 30,
            "INVALID_OAUTH", "Notion authorization could not be completed")
    state_hash = digest(state)
    with tx() as conn:
        pending = conn.execute("""SELECT s.*,a.active,a.role FROM provider_oauth_states s
                                  JOIN actors a ON a.id=s.actor_id
                                  WHERE s.state_hash=? AND s.provider='notion'""", (state_hash,)).fetchone()
        require(pending is not None and pending["used_at"] is None and pending["expires_at"] > now(),
                "INVALID_OAUTH", "Notion authorization could not be completed")
        require(pending["active"] == 1 and pending["role"] == "admin",
                "FORBIDDEN", "Only an active Admin can connect Notion")
    exchanger = exchanger or exchange_notion_code
    payload = await exchanger(code)
    require(isinstance(payload, dict), "PROVIDER_REJECTED", "Notion authorization failed")
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    workspace_id = payload.get("workspace_id")
    require(all(isinstance(value, str) and value for value in (access_token, refresh_token, workspace_id)),
            "PROVIDER_REJECTED", "Notion authorization response was incomplete")
    if discoverer is None:
        discovery = await discover_authorized_resources(access_token)
    else:
        discovery = await discoverer(access_token)
    require(isinstance(discovery, dict) and isinstance(discovery.get("resources"), list),
            "PROVIDER_REJECTED", "Notion authorized content could not be read")
    with tx() as conn:
        oauth_state = conn.execute("""SELECT s.*,a.active,a.role FROM provider_oauth_states s
                                      JOIN actors a ON a.id=s.actor_id
                                      WHERE s.state_hash=? AND s.provider='notion'""", (state_hash,)).fetchone()
        require(oauth_state is not None and oauth_state["used_at"] is None and oauth_state["expires_at"] > now(),
                "INVALID_OAUTH", "Notion authorization could not be completed")
        require(oauth_state["active"] == 1 and oauth_state["role"] == "admin",
                "FORBIDDEN", "Only an active Admin can connect Notion")
        existing = conn.execute("""SELECT * FROM provider_connections
                                   WHERE business_id=? AND provider='notion' AND environment='oauth'""",
                                (oauth_state["business_id"],)).fetchone()
        connection_id = existing["id"] if existing else new_id("pcn")
        credentials = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "bot_id": payload.get("bot_id"),
        }
        ciphertext, version = encrypt_credentials(credentials, _aad(connection_id, oauth_state["business_id"]))
        timestamp = now()
        permissions = json.dumps(["authorized_content:read"])
        workspace_name = str(payload.get("workspace_name") or "")[:200] or None
        account_ref = workspace_id[:200]
        if existing:
            conn.execute("""UPDATE provider_connections SET credentials_ciphertext=?,key_version=?,
                         permissions_json=?,provider_account_ref=?,status='active',verified_at=?,updated_at=?,revoked_at=NULL
                         WHERE id=?""",
                         (ciphertext, version, permissions, account_ref, timestamp, timestamp, connection_id))
        else:
            conn.execute("""INSERT INTO provider_connections
                         (id,business_id,provider,environment,credentials_ciphertext,key_version,permissions_json,
                          provider_account_ref,status,verified_at,created_at,updated_at,revoked_at)
                         VALUES(?,?,'notion','oauth',?,?,?,?,'active',?,?,?,NULL)""",
                         (connection_id, oauth_state["business_id"], ciphertext, version, permissions,
                          account_ref, timestamp, timestamp, timestamp))
        conn.execute("DELETE FROM provider_resources WHERE connection_id=?", (connection_id,))
        for resource in discovery["resources"][:MAX_DISCOVERY_ITEMS]:
            if not isinstance(resource, dict) or resource.get("type") not in ("page", "data_source"):
                continue
            resource_id = str(resource.get("id", ""))[:80]
            if not resource_id:
                continue
            metadata = {key: resource.get(key) for key in ("last_edited_time", "read_status")
                        if resource.get(key) is not None}
            conn.execute("""INSERT INTO provider_resources
                         (connection_id,business_id,provider,resource_id,resource_type,title,metadata_json,discovered_at)
                         VALUES(?,?,?,?,?,?,?,?)""",
                         (connection_id, oauth_state["business_id"], "notion", resource_id,
                          resource["type"], str(resource.get("title") or "Untitled")[:300],
                          json.dumps(metadata), timestamp))
        conn.execute("UPDATE provider_oauth_states SET used_at=? WHERE state_hash=?", (timestamp, state_hash))
    return {
        "connection_id": connection_id,
        "provider": "notion",
        "status": "active",
        "workspace_name": workspace_name,
        "authorized_resources": discovery["resources"][:MAX_DISCOVERY_ITEMS],
        "truncated": bool(discovery.get("truncated")),
    }


def load_notion_connection_for_business(business_id):
    with tx() as conn:
        row = conn.execute("""SELECT * FROM provider_connections
                              WHERE business_id=? AND provider='notion' AND environment='oauth'
                              AND status='active'""", (business_id,)).fetchone()
    if row is None:
        return None
    safe = rowdict(row)
    safe["credentials"] = decrypt_credentials(
        safe.pop("credentials_ciphertext"), safe["key_version"], _aad(safe["id"], safe["business_id"])
    )
    return safe


def _notion_url(page_id):
    return "https://www.notion.so/" + str(page_id).replace("-", "")


def _text_block(text, kind="paragraph"):
    return {"object": "block", "type": kind,
            kind: {"rich_text": [{"type": "text", "text": {"content": str(text)[:1900]}}]}}


def _sync_request(access_token, method, path, body=None, requester=None):
    if requester is not None:
        return requester(method, path, body)
    with httpx.Client(timeout=12.0) as client:
        response = client.request(method, NOTION_API_ROOT + path,
                                  headers=_headers(access_token), json=body)
    if response.status_code < 200 or response.status_code >= 300:
        if response.status_code == 403:
            raise ToolFailure("NOTION_WRITE_FORBIDDEN",
                              "Tally's Notion connection needs insert and update content access")
        raise ToolFailure("NOTION_SYNC_FAILED", "Notion could not be updated")
    try:
        return response.json()
    except ValueError as exc:
        raise ToolFailure("NOTION_SYNC_FAILED", "Notion returned an invalid response") from exc


def _create_child_page(access_token, parent_page_id, title, intro, requester=None):
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {"title": {"type": "title", "title": [
            {"type": "text", "text": {"content": title[:200]}}
        ]}},
        "children": [_text_block(intro)],
    }
    page = _sync_request(access_token, "POST", "/pages", payload, requester)
    page_id = str(page.get("id", "")) if isinstance(page, dict) else ""
    require(8 <= len(page_id) <= 80, "NOTION_SYNC_FAILED", "Notion did not create the requested page")
    return page_id


def initialize_notion_workspace_sync(session_token, parent_page_id, requester=None):
    """Create Tally's merchant-readable Notion structure after explicit Admin approval."""
    _enabled()
    require(isinstance(parent_page_id, str) and 8 <= len(parent_page_id) <= 80,
            "INVALID_INPUT", "Select an authorized Notion page for the Tally workspace")
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
        resource = conn.execute("""SELECT * FROM provider_resources WHERE business_id=?
                                   AND provider='notion' AND resource_id=? AND resource_type='page'""",
                                (actor["business_id"], parent_page_id)).fetchone()
        require(resource is not None, "NOT_FOUND",
                "Choose a page that this business authorized through Notion")
        existing = conn.execute("SELECT * FROM notion_workspaces WHERE business_id=?",
                                (actor["business_id"],)).fetchone()
        business = conn.execute("SELECT name FROM businesses WHERE id=?",
                                (actor["business_id"],)).fetchone()
    if existing is not None:
        require(existing["parent_page_id"] == parent_page_id, "ALREADY_CONFIGURED",
                "This business already has a different Notion workspace page")
        return {"status": "active", "created": False, "parent_page_id": parent_page_id,
                "workspace_url": _notion_url(parent_page_id)}
    connection = load_notion_connection_for_business(actor["business_id"])
    require(connection is not None, "NOT_CONNECTED", "Connect Notion first")
    access_token = connection["credentials"]["access_token"]
    business_name = business["name"]
    sections = {}
    definitions = (
        ("profile", "Business Profile", "Approved business identity, contact and operating details."),
        ("catalogue", "Catalogue", "Approved products, prices and stock snapshots from Tally."),
        ("policies", "Policies & FAQ", "Approved customer policies and frequently asked questions."),
        ("orders", "Orders", "Merchant-readable order and payment-status history. SQL remains authoritative."),
        ("activity", "Activity & Reconciliation", "Tally synchronization and reconciliation activity."),
    )
    for key, label, intro in definitions:
        sections[key] = _create_child_page(access_token, parent_page_id,
                                           f"{business_name} — {label}", intro, requester)
    timestamp = now()
    with tx() as conn:
        conn.execute("""INSERT INTO notion_workspaces
                     (business_id,connection_id,parent_page_id,profile_page_id,catalogue_page_id,
                      policies_page_id,orders_page_id,activity_page_id,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (actor["business_id"], connection["id"], parent_page_id,
                      sections["profile"], sections["catalogue"], sections["policies"],
                      sections["orders"], sections["activity"], timestamp, timestamp))
        permissions = set(json.loads(connection.get("permissions_json") or "[]"))
        permissions.update(("authorized_content:read", "insert_content", "update_content"))
        conn.execute("UPDATE provider_connections SET permissions_json=?,updated_at=? WHERE id=?",
                     (json.dumps(sorted(permissions)), timestamp, connection["id"]))
        for key, page_id in sections.items():
            conn.execute("""INSERT OR REPLACE INTO provider_resources
                         (connection_id,business_id,provider,resource_id,resource_type,title,
                          metadata_json,discovered_at) VALUES(?,?,?,?,?,?,?,?)""",
                         (connection["id"], actor["business_id"], "notion", page_id, "page",
                          key, json.dumps({"managed_by": "tally"}), timestamp))
    return {"status": "active", "created": True, "parent_page_id": parent_page_id,
            "workspace_url": _notion_url(parent_page_id), "sections": sorted(sections)}


def _workspace_snapshot(business_id):
    with tx() as conn:
        workspace = conn.execute("SELECT * FROM notion_workspaces WHERE business_id=?",
                                 (business_id,)).fetchone()
    return rowdict(workspace) if workspace is not None else None


def _append_blocks(connection, page_id, blocks, requester=None):
    return _sync_request(connection["credentials"]["access_token"], "PATCH",
                         f"/blocks/{page_id}/children",
                         {"children": blocks[:100], "notifications": {"mode": "silent"}}, requester)


def sync_business_snapshot(session_token, requester=None):
    """Mirror an already-approved SQL profile/policy snapshot into the merchant workspace."""
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
        business = conn.execute("SELECT * FROM businesses WHERE id=?", (actor["business_id"],)).fetchone()
        settings = conn.execute("SELECT * FROM business_settings WHERE business_id=?",
                                (actor["business_id"],)).fetchone()
    workspace = _workspace_snapshot(actor["business_id"])
    if workspace is None:
        return {"status": "not_configured"}
    connection = load_notion_connection_for_business(actor["business_id"])
    require(connection is not None, "NOT_CONNECTED", "Notion connection is unavailable")
    timestamp = now()
    profile = json.loads(settings["profile_json"] or "{}")
    profile_lines = [f"Approved profile snapshot — {timestamp}", f"Business: {business['name']}"]
    profile_lines.extend(f"{key}: {value}" for key, value in sorted(profile.items()))
    _append_blocks(connection, workspace["profile_page_id"],
                   [_text_block(line) for line in profile_lines], requester)
    policies = json.loads(settings["policies_json"] or "[]")
    policy_lines = [f"Approved policies snapshot — {timestamp}"]
    policy_lines.extend(f"{item.get('question', '')}: {item.get('answer', '')}" for item in policies)
    _append_blocks(connection, workspace["policies_page_id"],
                   [_text_block(line) for line in policy_lines], requester)
    _append_blocks(connection, workspace["activity_page_id"],
                   [_text_block(f"{timestamp} — Approved profile/policies synchronized.")], requester)
    return {"status": "synced", "workspace_url": _notion_url(workspace["parent_page_id"])}


def _sync_record_page(business_id, record_type, record_id, parent_page_id, title, lines, requester=None):
    connection = load_notion_connection_for_business(business_id)
    require(connection is not None, "NOT_CONNECTED", "Notion connection is unavailable")
    with tx() as conn:
        record = conn.execute("""SELECT notion_page_id FROM notion_records
                                 WHERE business_id=? AND record_type=? AND record_id=?""",
                              (business_id, record_type, record_id)).fetchone()
    if record is None:
        page_id = _create_child_page(connection["credentials"]["access_token"], parent_page_id,
                                     title, lines[0], requester)
        remaining = lines[1:]
        with tx() as conn:
            conn.execute("INSERT INTO notion_records VALUES(?,?,?,?,?)",
                         (business_id, record_type, record_id, page_id, now()))
    else:
        page_id = record["notion_page_id"]
        remaining = lines
    if remaining:
        _append_blocks(connection, page_id, [_text_block(line) for line in remaining], requester)
    with tx() as conn:
        conn.execute("UPDATE notion_records SET updated_at=? WHERE business_id=? AND record_type=? AND record_id=?",
                     (now(), business_id, record_type, record_id))
    return page_id


def sync_product_snapshot(session_token, product_id, requester=None):
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
        product = conn.execute("SELECT * FROM products WHERE id=? AND business_id=?",
                               (product_id, actor["business_id"])).fetchone()
        require(product is not None, "NOT_FOUND", "Product not found")
    workspace = _workspace_snapshot(actor["business_id"])
    if workspace is None:
        return {"status": "not_configured"}
    timestamp = now()
    lines = [f"Approved catalogue update — {timestamp}",
             f"Price: {product['currency']} {product['price_minor'] / 100:,.2f}",
             f"Stock on hand: {product['stock_on_hand']}",
             f"Reserved: {product['stock_reserved']}",
             f"Low-stock threshold: {product['low_stock_threshold']}"]
    page_id = _sync_record_page(actor["business_id"], "product", product_id,
                                workspace["catalogue_page_id"], product["name"], lines, requester)
    return {"status": "synced", "record_url": _notion_url(page_id)}


def sync_order_snapshot(order_id, requester=None):
    with tx() as conn:
        order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        require(order is not None, "NOT_FOUND", "Order not found")
    workspace = _workspace_snapshot(order["business_id"])
    if workspace is None:
        return {"status": "not_configured"}
    lines = [f"Order update — {now()}", f"Status: {order['status']}",
             f"Total: {order['currency']} {order['total_minor'] / 100:,.2f}",
             f"Created: {order['created_at']}", f"Last updated: {order['updated_at']}"]
    page_id = _sync_record_page(order["business_id"], "order", order_id,
                                workspace["orders_page_id"], f"Order {order_id}", lines, requester)
    return {"status": "synced", "record_url": _notion_url(page_id)}


async def refresh_notion_connection(connection_id, refresher=None):
    """Rotate both Notion OAuth tokens and replace the encrypted credential atomically."""
    with tx() as conn:
        row = conn.execute("""SELECT * FROM provider_connections
                              WHERE id=? AND provider='notion' AND environment='oauth'
                              AND status='active'""", (connection_id,)).fetchone()
    require(row is not None, "NOT_CONNECTED", "Notion connection is unavailable")
    current = rowdict(row)
    credentials = decrypt_credentials(
        current["credentials_ciphertext"], current["key_version"],
        _aad(current["id"], current["business_id"]),
    )
    refresh_token = credentials.get("refresh_token")
    require(isinstance(refresh_token, str) and refresh_token,
            "NOT_CONNECTED", "Notion connection cannot be refreshed")
    refresher = refresher or exchange_notion_refresh_token
    payload = await refresher(refresh_token)
    new_access = payload.get("access_token") if isinstance(payload, dict) else None
    new_refresh = payload.get("refresh_token") if isinstance(payload, dict) else None
    require(all(isinstance(value, str) and value for value in (new_access, new_refresh)),
            "PROVIDER_REJECTED", "Notion refresh response was incomplete")
    updated_credentials = {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "bot_id": payload.get("bot_id") or credentials.get("bot_id"),
    }
    ciphertext, version = encrypt_credentials(
        updated_credentials, _aad(current["id"], current["business_id"])
    )
    with tx() as conn:
        active = conn.execute("""SELECT id FROM provider_connections
                                 WHERE id=? AND provider='notion' AND environment='oauth'
                                 AND status='active'""", (connection_id,)).fetchone()
        require(active is not None, "NOT_CONNECTED", "Notion connection is unavailable")
        conn.execute("""UPDATE provider_connections SET credentials_ciphertext=?,key_version=?,
                     updated_at=? WHERE id=?""", (ciphertext, version, now(), connection_id))
    return load_notion_connection_for_business(current["business_id"])


def _property_value(prop):
    if not isinstance(prop, dict):
        return None
    kind = prop.get("type")
    value = prop.get(kind) if isinstance(kind, str) else None
    if kind in ("title", "rich_text"):
        return _plain_text(value)
    if kind in ("number", "checkbox", "url", "email", "phone_number"):
        return value
    if kind in ("select", "status") and isinstance(value, dict):
        return str(value.get("name", ""))[:MAX_TEXT_CHARS]
    if kind == "multi_select" and isinstance(value, list):
        return [str(item.get("name", ""))[:100] for item in value[:30] if isinstance(item, dict)]
    if kind == "date" and isinstance(value, dict):
        return {key: str(value.get(key, ""))[:80] or None for key in ("start", "end", "time_zone")}
    return None


def _page_properties(page):
    properties = page.get("properties") if isinstance(page, dict) else None
    if not isinstance(properties, dict):
        return {}
    result = {}
    for name, prop in list(properties.items())[:80]:
        value = _property_value(prop)
        if value not in (None, "", [], {}):
            result[str(name)[:160]] = value
    return result


def _block_text(block):
    if not isinstance(block, dict):
        return None
    kind = block.get("type")
    value = block.get(kind) if isinstance(kind, str) else None
    if not isinstance(value, dict):
        return None
    text = _plain_text(value.get("rich_text"))
    if not text and kind in ("child_page", "child_database"):
        text = str(value.get("title", ""))[:MAX_TEXT_CHARS]
    if not text:
        return None
    return {"type": str(kind)[:80], "text": text}


async def preview_notion_resource(session_token, resource_id, requester=None):
    """Read one currently authorized page/data source and return a bounded data preview."""
    _enabled()
    require(isinstance(resource_id, str) and 8 <= len(resource_id) <= 80,
            "INVALID_INPUT", "Select a valid Notion resource")
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
    connection = load_notion_connection_for_business(actor["business_id"])
    require(connection is not None, "NOT_CONNECTED", "Connect Notion first")
    access_token = connection["credentials"]["access_token"]

    async def request(method, path, body=None):
        nonlocal connection, access_token
        if requester is not None:
            return await requester(method, path, body)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, NOTION_API_ROOT + path, headers=_headers(access_token), json=body)
        if response.status_code == 401:
            connection = await refresh_notion_connection(connection["id"])
            access_token = connection["credentials"]["access_token"]
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.request(method, NOTION_API_ROOT + path,
                                                headers=_headers(access_token), json=body)
        if response.status_code != 200:
            raise ValueError("Notion resource could not be read")
        return response.json()

    search = await request("POST", "/search", {"page_size": MAX_DISCOVERY_ITEMS})
    resources = search.get("results") if isinstance(search, dict) else None
    require(isinstance(resources, list), "PROVIDER_REJECTED", "Notion returned an invalid content response")
    selected = next((item for item in resources if isinstance(item, dict) and item.get("id") == resource_id
                     and item.get("object") in ("page", "data_source")), None)
    require(selected is not None, "NOT_FOUND", "Resource is not in this business's authorized Notion content")

    if selected["object"] == "data_source":
        payload = await request("POST", f"/data_sources/{resource_id}/query", {"page_size": MAX_PREVIEW_ROWS})
        rows = payload.get("results") if isinstance(payload, dict) else None
        require(isinstance(rows, list), "PROVIDER_REJECTED", "Notion returned an invalid data source response")
        return {
            "source": {**_resource_summary(selected), "workspace": "authorized OAuth workspace"},
            "rows": [{"id": str(row.get("id", ""))[:80], "properties": _page_properties(row)}
                     for row in rows[:MAX_PREVIEW_ROWS] if isinstance(row, dict)],
            "truncated": bool(payload.get("has_more")),
            "notice": "Preview only. Notion content is untrusted merchant data and has not been imported.",
        }

    page = await request("GET", f"/pages/{resource_id}")
    blocks = await request("GET", f"/blocks/{resource_id}/children?page_size={MAX_PREVIEW_BLOCKS}")
    block_items = blocks.get("results") if isinstance(blocks, dict) else None
    require(isinstance(block_items, list), "PROVIDER_REJECTED", "Notion returned an invalid page response")
    return {
        "source": {**_resource_summary(selected), "workspace": "authorized OAuth workspace"},
        "properties": _page_properties(page),
        "content": [value for value in (_block_text(block) for block in block_items[:MAX_PREVIEW_BLOCKS]) if value],
        "truncated": bool(blocks.get("has_more")),
        "notice": "Preview only. Notion content is untrusted merchant data and has not been imported.",
    }


def preview_notion_resource_sync(session_token, resource_id, requester=None):
    """Synchronous MCP variant of the bounded preview used during Desk onboarding."""
    _enabled()
    require(isinstance(resource_id, str) and 8 <= len(resource_id) <= 80,
            "INVALID_INPUT", "Select a valid Notion resource")
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
    connection = load_notion_connection_for_business(actor["business_id"])
    require(connection is not None, "NOT_CONNECTED", "Connect Notion first")
    access_token = connection["credentials"]["access_token"]

    def request(method, path, body=None):
        if requester is not None:
            return requester(method, path, body)
        with httpx.Client(timeout=10.0) as client:
            response = client.request(method, NOTION_API_ROOT + path,
                                      headers=_headers(access_token), json=body)
        if response.status_code != 200:
            raise ValueError("Notion resource could not be read")
        return response.json()

    search = request("POST", "/search", {"page_size": MAX_DISCOVERY_ITEMS})
    resources = search.get("results") if isinstance(search, dict) else None
    require(isinstance(resources, list), "PROVIDER_REJECTED", "Notion returned invalid content")
    selected = next((item for item in resources if isinstance(item, dict) and item.get("id") == resource_id
                     and item.get("object") in ("page", "data_source")), None)
    require(selected is not None, "NOT_FOUND", "Resource is not in this business's authorized Notion content")
    if selected["object"] == "data_source":
        payload = request("POST", f"/data_sources/{resource_id}/query", {"page_size": MAX_PREVIEW_ROWS})
        rows = payload.get("results") if isinstance(payload, dict) else None
        require(isinstance(rows, list), "PROVIDER_REJECTED", "Notion returned invalid data source content")
        return {"source": {**_resource_summary(selected), "workspace": "authorized OAuth workspace"},
                "rows": [{"id": str(row.get("id", ""))[:80], "properties": _page_properties(row)}
                         for row in rows[:MAX_PREVIEW_ROWS] if isinstance(row, dict)],
                "truncated": bool(payload.get("has_more")),
                "notice": "Preview only. Import requires explicit Admin approval."}
    page = request("GET", f"/pages/{resource_id}")
    blocks = request("GET", f"/blocks/{resource_id}/children?page_size={MAX_PREVIEW_BLOCKS}")
    block_items = blocks.get("results") if isinstance(blocks, dict) else None
    require(isinstance(block_items, list), "PROVIDER_REJECTED", "Notion returned invalid page content")
    return {"source": {**_resource_summary(selected), "workspace": "authorized OAuth workspace"},
            "properties": _page_properties(page),
            "content": [value for value in (_block_text(block) for block in block_items[:MAX_PREVIEW_BLOCKS]) if value],
            "truncated": bool(blocks.get("has_more")),
            "notice": "Preview only. Import requires explicit Admin approval."}
