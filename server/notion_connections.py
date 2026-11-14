"""Business-scoped Notion OAuth and bounded, read-only content previews."""
import json
import os
import re
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
    parent = item.get("parent") if isinstance(item, dict) else None
    parent_type = parent.get("type") if isinstance(parent, dict) else None
    parent_id = parent.get(parent_type) if parent_type in ("page_id", "database_id") else None
    result = {
        "id": str(item.get("id", ""))[:80],
        "type": item.get("object") if item.get("object") in ("page", "data_source") else "unknown",
        "title": _title(item),
        "last_edited_time": str(item.get("last_edited_time", ""))[:40] or None,
    }
    if parent_type:
        result["parent_type"] = str(parent_type)[:40]
    if parent_id:
        result["parent_id"] = str(parent_id)[:80]
    return result


async def discover_authorized_resources(access_token, requester=None):
    """List authorized roots plus readable direct children, then probe bounded access."""
    async def request(method, path, body=None):
        if requester is not None:
            return await requester(method, path, body)
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method, NOTION_API_ROOT + path, headers=_headers(access_token), json=body
            )
        if response.status_code != 200:
            return None
        return response.json()

    payload = await request("POST", "/search", {"page_size": MAX_DISCOVERY_ITEMS})
    if payload is None:
        raise ValueError("Notion authorized content could not be read")
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise ValueError("Notion returned an invalid content response")
    summaries = [_resource_summary(item) for item in results[:MAX_DISCOVERY_ITEMS]
                 if isinstance(item, dict) and item.get("object") in ("page", "data_source")]
    known = {summary["id"] for summary in summaries}
    truncated = bool(payload.get("has_more"))

    # Notion search may return only the OAuth-selected root even when its direct
    # child pages and databases inherit access. Discover one bounded child level
    # so a merchant can share a single business workspace root.
    for root in [item for item in summaries if item["type"] == "page"][:10]:
        blocks = await request("GET", f"/blocks/{root['id']}/children?page_size={MAX_DISCOVERY_ITEMS}")
        if not isinstance(blocks, dict) or not isinstance(blocks.get("results"), list):
            continue
        truncated = truncated or bool(blocks.get("has_more"))
        for block in blocks["results"][:MAX_DISCOVERY_ITEMS]:
            if not isinstance(block, dict) or len(summaries) >= MAX_DISCOVERY_ITEMS:
                continue
            kind = block.get("type")
            child_id = str(block.get("id", ""))[:80]
            if kind == "child_page" and child_id and child_id not in known:
                title = str((block.get("child_page") or {}).get("title") or "Untitled page")[:300]
                summaries.append({"id": child_id, "type": "page", "title": title,
                                  "last_edited_time": None,
                                  "parent_type": "page_id", "parent_id": root["id"]})
                known.add(child_id)
            elif kind == "child_database" and child_id:
                database = await request("GET", f"/databases/{child_id}")
                data_sources = database.get("data_sources") if isinstance(database, dict) else None
                if not isinstance(data_sources, list):
                    continue
                for source in data_sources:
                    if not isinstance(source, dict) or len(summaries) >= MAX_DISCOVERY_ITEMS:
                        continue
                    source_id = str(source.get("id", ""))[:80]
                    if not source_id or source_id in known:
                        continue
                    title = str(source.get("name") or
                                (block.get("child_database") or {}).get("title") or
                                "Untitled data source")[:300]
                    summaries.append({"id": source_id, "type": "data_source", "title": title,
                                      "last_edited_time": None,
                                      "parent_type": "page_id", "parent_id": root["id"]})
                    known.add(source_id)

    for summary in summaries[:5]:
        try:
            if summary["type"] == "page":
                probe = await request("GET", f"/blocks/{summary['id']}/children?page_size=1")
            else:
                probe = await request("POST", f"/data_sources/{summary['id']}/query", {"page_size": 1})
            summary["read_status"] = "readable" if isinstance(probe, dict) else "unreadable"
        except httpx.HTTPError:
            summary["read_status"] = "unreadable"
    return {"resources": summaries, "truncated": truncated}


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
        # Retain Tally-owned pages so a retried OAuth callback can resume a
        # partially completed workspace setup instead of creating duplicates.
        existing_resources = conn.execute(
            "SELECT * FROM provider_resources WHERE connection_id=?", (connection_id,)
        ).fetchall()
        managed_resources = []
        for existing_resource in existing_resources:
            try:
                metadata = json.loads(existing_resource["metadata_json"] or "{}")
            except ValueError:
                metadata = {}
            if metadata.get("managed_by") == "tally":
                managed_resources.append(existing_resource)
        managed_ids = {row["resource_id"] for row in managed_resources}
        conn.execute("DELETE FROM provider_resources WHERE connection_id=?", (connection_id,))
        for managed_resource in managed_resources:
            conn.execute("""INSERT INTO provider_resources
                         (connection_id,business_id,provider,resource_id,resource_type,title,
                          metadata_json,discovered_at) VALUES(?,?,?,?,?,?,?,?)""",
                         tuple(managed_resource[key] for key in (
                             "connection_id", "business_id", "provider", "resource_id",
                             "resource_type", "title", "metadata_json", "discovered_at")))
        for resource in discovery["resources"][:MAX_DISCOVERY_ITEMS]:
            if not isinstance(resource, dict) or resource.get("type") not in ("page", "data_source"):
                continue
            resource_id = str(resource.get("id", ""))[:80]
            if not resource_id or resource_id in managed_ids:
                continue
            metadata = {key: resource.get(key) for key in
                        ("last_edited_time", "read_status", "parent_type", "parent_id")
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
        "business_id": oauth_state["business_id"],
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


def select_notion_workspace_parent(business_id):
    """Choose the one OAuth-authorized root page intended as this business workspace."""
    with tx() as conn:
        business = conn.execute("SELECT name FROM businesses WHERE id=?", (business_id,)).fetchone()
        resources = conn.execute("""SELECT resource_id,title,metadata_json FROM provider_resources
                                  WHERE business_id=? AND provider='notion' AND resource_type='page'""",
                                 (business_id,)).fetchall()
    require(business is not None, "NOT_FOUND", "Business not found")
    require(resources, "NOTION_WORKSPACE_REQUIRED",
            "Select a Notion page for Tally's managed workspace")
    page_ids = {item["resource_id"] for item in resources}
    candidates = []
    for item in resources:
        try:
            metadata = json.loads(item["metadata_json"] or "{}")
        except ValueError:
            metadata = {}
        if metadata.get("managed_by") != "tally" and metadata.get("parent_id") not in page_ids:
            candidates.append(item)
    if len(candidates) == 1:
        return candidates[0]["resource_id"]
    normalized_business = re.sub(r"[^a-z0-9]+", "", business["name"].lower())
    preferred = []
    for item in candidates or resources:
        title = re.sub(r"[^a-z0-9]+", "", item["title"].lower())
        if normalized_business and normalized_business in title and "workspace" in title:
            preferred.append(item)
    require(len(preferred) == 1, "NOTION_WORKSPACE_AMBIGUOUS",
            "Select one business workspace page when connecting Notion")
    return preferred[0]["resource_id"]


def initialize_notion_workspace_for_business(business_id, parent_page_id, requester=None,
                                             backfill=True):
    """Create managed sections after the Admin consents on Tally's OAuth linking page."""
    _enabled()
    require(isinstance(parent_page_id, str) and 8 <= len(parent_page_id) <= 80,
            "INVALID_INPUT", "Select an authorized Notion page for the Tally workspace")
    with tx() as conn:
        resource = conn.execute("""SELECT * FROM provider_resources WHERE business_id=?
                                   AND provider='notion' AND resource_id=? AND resource_type='page'""",
                                (business_id, parent_page_id)).fetchone()
        require(resource is not None, "NOT_FOUND",
                "Choose a page that this business authorized through Notion")
        existing = conn.execute("SELECT * FROM notion_workspaces WHERE business_id=?",
                                (business_id,)).fetchone()
        business = conn.execute("SELECT name FROM businesses WHERE id=?",
                                (business_id,)).fetchone()
    if existing is not None:
        require(existing["parent_page_id"] == parent_page_id, "ALREADY_CONFIGURED",
                "This business already has a different Notion workspace page")
        connection = load_notion_connection_for_business(business_id)
        require(connection is not None, "NOT_CONNECTED", "Connect Notion first")
        permissions = set(json.loads(connection.get("permissions_json") or "[]"))
        permissions.update(("authorized_content:read", "insert_content", "update_content"))
        with tx() as conn:
            conn.execute("UPDATE provider_connections SET permissions_json=?,updated_at=? WHERE id=?",
                         (json.dumps(sorted(permissions)), now(), connection["id"]))
        result = {"status": "active", "created": False, "parent_page_id": parent_page_id,
                  "workspace_url": _notion_url(parent_page_id)}
        if backfill:
            result["backfill"] = sync_notion_business_history(business_id, requester=requester)
        return result
    connection = load_notion_connection_for_business(business_id)
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
    with tx() as conn:
        existing_resources = conn.execute("""SELECT resource_id,title,metadata_json
                                               FROM provider_resources
                                               WHERE business_id=? AND connection_id=?
                                               AND provider='notion' AND resource_type='page'""",
                                          (business_id, connection["id"])).fetchall()
    reusable = {}
    for resource in existing_resources:
        try:
            metadata = json.loads(resource["metadata_json"] or "{}")
        except ValueError:
            metadata = {}
        section = metadata.get("managed_section")
        if (metadata.get("managed_by") == "tally" and
                metadata.get("parent_id", parent_page_id) == parent_page_id):
            reusable[section or resource["title"]] = resource["resource_id"]
    for key, label, intro in definitions:
        if key in reusable:
            sections[key] = reusable[key]
            continue
        page_id = _create_child_page(access_token, parent_page_id,
                                     f"{business_name} — {label}", intro, requester)
        sections[key] = page_id
        timestamp = now()
        with tx() as conn:
            conn.execute("""INSERT OR REPLACE INTO provider_resources
                         (connection_id,business_id,provider,resource_id,resource_type,title,
                          metadata_json,discovered_at) VALUES(?,?, 'notion',?,'page',?,?,?)""",
                         (connection["id"], business_id, page_id, key,
                          json.dumps({"managed_by": "tally", "managed_section": key,
                                      "parent_id": parent_page_id}), timestamp))
    timestamp = now()
    with tx() as conn:
        conn.execute("""INSERT INTO notion_workspaces
                     (business_id,connection_id,parent_page_id,profile_page_id,catalogue_page_id,
                      policies_page_id,orders_page_id,activity_page_id,created_at,updated_at)
                     VALUES(?,?,?,?,?,?,?,?,?,?)""",
                     (business_id, connection["id"], parent_page_id,
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
                         (connection["id"], business_id, "notion", page_id, "page",
                          key, json.dumps({"managed_by": "tally", "managed_section": key,
                                           "parent_id": parent_page_id}), timestamp))
    result = {"status": "active", "created": True, "parent_page_id": parent_page_id,
              "workspace_url": _notion_url(parent_page_id), "sections": sorted(sections)}
    if backfill:
        result["backfill"] = sync_notion_business_history(business_id, requester=requester)
    return result


def trash_managed_notion_pages_for_business(business_id, requester=None):
    """Move only Tally-owned Notion sections and record pages to the workspace trash.

    The merchant-selected parent and all merchant-authored source pages are
    deliberately excluded. IDs come only from Tally's ownership manifest.
    """
    with tx() as conn:
        workspace = conn.execute("SELECT * FROM notion_workspaces WHERE business_id=?",
                                 (business_id,)).fetchone()
        records = conn.execute("SELECT notion_page_id FROM notion_records WHERE business_id=?",
                               (business_id,)).fetchall()
        resources = conn.execute("""SELECT resource_id,metadata_json FROM provider_resources
                                  WHERE business_id=? AND provider='notion'""",
                                 (business_id,)).fetchall()
    record_pages = [row["notion_page_id"] for row in records if row["notion_page_id"]]
    section_pages = []
    if workspace is not None:
        section_pages.extend(workspace[key] for key in (
            "profile_page_id", "catalogue_page_id", "policies_page_id",
            "orders_page_id", "activity_page_id") if workspace[key])
    for resource in resources:
        try:
            metadata = json.loads(resource["metadata_json"] or "{}")
        except ValueError:
            metadata = {}
        if metadata.get("managed_by") == "tally":
            section_pages.append(resource["resource_id"])
    page_ids = list(dict.fromkeys(record_pages + section_pages))
    if not page_ids:
        return {"status": "not_configured", "trashed_pages": 0}

    connection = load_notion_connection_for_business(business_id)
    require(connection is not None, "NOTION_RESET_UNAVAILABLE",
            "Tally-owned Notion pages cannot be removed without the active connection")
    access_token = connection["credentials"]["access_token"]
    for page_id in page_ids:
        result = _sync_request(access_token, "PATCH", f"/pages/{page_id}",
                               {"in_trash": True}, requester)
        require(isinstance(result, dict) and result.get("in_trash") is True,
                "NOTION_RESET_FAILED", "Notion did not confirm removal of a Tally-owned page")
    return {"status": "trashed", "trashed_pages": len(page_ids)}


def initialize_notion_workspace_sync(session_token, parent_page_id, requester=None):
    """Compatibility wrapper for an authenticated Admin-triggered workspace setup."""
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
    return initialize_notion_workspace_for_business(
        actor["business_id"], parent_page_id, requester=requester, backfill=False)


def _workspace_snapshot(business_id):
    with tx() as conn:
        workspace = conn.execute("SELECT * FROM notion_workspaces WHERE business_id=?",
                                 (business_id,)).fetchone()
    return rowdict(workspace) if workspace is not None else None


def _append_blocks(connection, page_id, blocks, requester=None):
    return _sync_request(connection["credentials"]["access_token"], "PATCH",
                         f"/blocks/{page_id}/children",
                         {"children": blocks[:100], "notifications": {"mode": "silent"}}, requester)


def _sync_business_snapshot_for_business(business_id, requester=None):
    with tx() as conn:
        business = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
        settings = conn.execute("SELECT * FROM business_settings WHERE business_id=?",
                                (business_id,)).fetchone()
    workspace = _workspace_snapshot(business_id)
    if workspace is None:
        return {"status": "not_configured"}
    connection = load_notion_connection_for_business(business_id)
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


def sync_business_snapshot(session_token, requester=None):
    """Mirror an already-approved SQL profile/policy snapshot into the merchant workspace."""
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
    return _sync_business_snapshot_for_business(actor["business_id"], requester=requester)


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


def _sync_product_snapshot_for_business(business_id, product_id, requester=None):
    with tx() as conn:
        product = conn.execute("SELECT * FROM products WHERE id=? AND business_id=?",
                               (product_id, business_id)).fetchone()
        require(product is not None, "NOT_FOUND", "Product not found")
    workspace = _workspace_snapshot(business_id)
    if workspace is None:
        return {"status": "not_configured"}
    timestamp = now()
    lines = [f"Approved catalogue update — {timestamp}",
             f"Price: {product['currency']} {product['price_minor'] / 100:,.2f}",
             f"Stock on hand: {product['stock_on_hand']}",
             f"Reserved: {product['stock_reserved']}",
             f"Low-stock threshold: {product['low_stock_threshold']}"]
    page_id = _sync_record_page(business_id, "product", product_id,
                                workspace["catalogue_page_id"], product["name"], lines, requester)
    return {"status": "synced", "record_url": _notion_url(page_id)}


def sync_product_snapshot(session_token, product_id, requester=None):
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        require_role(actor, "admin")
    return _sync_product_snapshot_for_business(actor["business_id"], product_id, requester=requester)


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


def sync_support_case_snapshot(case_id, requester=None):
    """Mirror a customer dispute or inquiry into Activity & Reconciliation."""
    with tx() as conn:
        case = conn.execute("SELECT * FROM support_cases WHERE id=?", (case_id,)).fetchone()
        require(case is not None, "NOT_FOUND", "Support case not found")
        messages = conn.execute("""SELECT sender_kind,body,created_at FROM support_messages
                                  WHERE case_id=? ORDER BY created_at""", (case_id,)).fetchall()
    workspace = _workspace_snapshot(case["business_id"])
    if workspace is None:
        return {"status": "not_configured"}
    lines = [f"Support update — {now()}", f"Type: {case['category']}",
             f"Status: {case['status']}", f"Opened: {case['opened_at']}"]
    if case["order_id"]:
        lines.append(f"Order: {case['order_id']}")
    lines.extend(f"{message['created_at']} — {message['sender_kind']}: {message['body']}"
                 for message in messages[-20:])
    page_id = _sync_record_page(case["business_id"], "support_case", case_id,
                                workspace["activity_page_id"],
                                f"Support case {case_id}", lines, requester)
    return {"status": "synced", "record_url": _notion_url(page_id)}


def sync_notion_business_history(business_id, requester=None):
    """Populate a newly linked workspace from current SQL-authoritative records."""
    with tx() as conn:
        product_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM products WHERE business_id=? ORDER BY name LIMIT 200", (business_id,))]
        order_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM orders WHERE business_id=? ORDER BY created_at LIMIT 200", (business_id,))]
        case_ids = [row["id"] for row in conn.execute(
            "SELECT id FROM support_cases WHERE business_id=? ORDER BY opened_at LIMIT 200", (business_id,))]
    _sync_business_snapshot_for_business(business_id, requester=requester)
    for product_id in product_ids:
        _sync_product_snapshot_for_business(business_id, product_id, requester=requester)
    for order_id in order_ids:
        sync_order_snapshot(order_id, requester=requester)
    for case_id in case_ids:
        sync_support_case_snapshot(case_id, requester=requester)
    return {"profile": 1, "products": len(product_ids), "orders": len(order_ids),
            "support_cases": len(case_ids)}


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


def _authorized_resource(conn, business_id, resource_reference):
    """Resolve an authorized resource ID, or an exact title supplied by Desk.

    Resource titles are only resolved inside the business's OAuth allowlist.  This
    keeps preview authorization server-side while making the API robust when an
    agent passes the human-readable title returned by discovery instead of its ID.
    """
    columns = "resource_id,resource_type,title,metadata_json"
    authorized = conn.execute(
        f"""SELECT {columns} FROM provider_resources
             WHERE business_id=? AND provider='notion' AND resource_id=?""",
        (business_id, resource_reference),
    ).fetchone()
    if authorized is not None:
        return authorized
    matches = conn.execute(
        f"""SELECT {columns} FROM provider_resources
             WHERE business_id=? AND provider='notion'
             AND lower(trim(title))=lower(trim(?))
             ORDER BY resource_id""",
        (business_id, resource_reference),
    ).fetchall()
    if not matches:
        return None

    reference = resource_reference.strip().lower()
    preferred_type = "data_source" if "catalog" in reference else "page"

    def rank(row):
        metadata = json.loads(row["metadata_json"] or "{}")
        return (
            row["resource_type"] != preferred_type,
            metadata.get("managed_by") == "tally",
            row["resource_id"],
        )

    return sorted(matches, key=rank)[0]


async def preview_notion_resource(session_token, resource_id, requester=None):
    """Read one currently authorized page/data source and return a bounded data preview."""
    _enabled()
    require(isinstance(resource_id, str) and 8 <= len(resource_id) <= 80,
            "INVALID_INPUT", "Select a valid Notion resource")
    with tx() as conn:
        actor = actor_from_token(conn, session_token, "desk")
        authorized = _authorized_resource(conn, actor["business_id"], resource_id)
    require(authorized is not None, "NOT_FOUND",
            "Resource is not in this business's authorized Notion content")
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

    source = {"id": authorized["resource_id"], "type": authorized["resource_type"],
              "title": authorized["title"], "workspace": "authorized OAuth workspace"}
    resolved_id = authorized["resource_id"]

    if authorized["resource_type"] == "data_source":
        payload = await request("POST", f"/data_sources/{resolved_id}/query", {"page_size": MAX_PREVIEW_ROWS})
        rows = payload.get("results") if isinstance(payload, dict) else None
        require(isinstance(rows, list), "PROVIDER_REJECTED", "Notion returned an invalid data source response")
        return {
            "source": source,
            "rows": [{"id": str(row.get("id", ""))[:80], "properties": _page_properties(row)}
                     for row in rows[:MAX_PREVIEW_ROWS] if isinstance(row, dict)],
            "truncated": bool(payload.get("has_more")),
            "notice": "Preview only. Notion content is untrusted merchant data and has not been imported.",
        }

    page = await request("GET", f"/pages/{resolved_id}")
    blocks = await request("GET", f"/blocks/{resolved_id}/children?page_size={MAX_PREVIEW_BLOCKS}")
    block_items = blocks.get("results") if isinstance(blocks, dict) else None
    require(isinstance(block_items, list), "PROVIDER_REJECTED", "Notion returned an invalid page response")
    return {
        "source": source,
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
        authorized = _authorized_resource(conn, actor["business_id"], resource_id)
    require(authorized is not None, "NOT_FOUND",
            "Resource is not in this business's authorized Notion content")
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

    source = {"id": authorized["resource_id"], "type": authorized["resource_type"],
              "title": authorized["title"], "workspace": "authorized OAuth workspace"}
    resolved_id = authorized["resource_id"]
    if authorized["resource_type"] == "data_source":
        payload = request("POST", f"/data_sources/{resolved_id}/query", {"page_size": MAX_PREVIEW_ROWS})
        rows = payload.get("results") if isinstance(payload, dict) else None
        require(isinstance(rows, list), "PROVIDER_REJECTED", "Notion returned invalid data source content")
        return {"source": source,
                "rows": [{"id": str(row.get("id", ""))[:80], "properties": _page_properties(row)}
                         for row in rows[:MAX_PREVIEW_ROWS] if isinstance(row, dict)],
                "truncated": bool(payload.get("has_more")),
                "notice": "Preview only. Import requires explicit Admin approval."}
    page = request("GET", f"/pages/{resolved_id}")
    blocks = request("GET", f"/blocks/{resolved_id}/children?page_size={MAX_PREVIEW_BLOCKS}")
    block_items = blocks.get("results") if isinstance(blocks, dict) else None
    require(isinstance(block_items, list), "PROVIDER_REJECTED", "Notion returned invalid page content")
    return {"source": source,
            "properties": _page_properties(page),
            "content": [value for value in (_block_text(block) for block in block_items[:MAX_PREVIEW_BLOCKS]) if value],
            "truncated": bool(blocks.get("has_more")),
            "notice": "Preview only. Import requires explicit Admin approval."}
