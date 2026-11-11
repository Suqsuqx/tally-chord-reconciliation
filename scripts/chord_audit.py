#!/usr/bin/env python3
"""Read-only, redacted Chord teammate/MCP scope and connectivity audit."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE = "https://api.chordhq.xyz/v1"
EXPECTED_TOOLS = {
    "Tally Sandbox Shop": {
        "link_identity",
        "get_catalog",
        "create_order",
        "get_my_order",
        "record_payment_claim",
        "create_support_case",
        "get_my_support_case",
    },
    "Tally Sandbox Desk": {
        "link_identity",
        "get_catalog",
        "upsert_product",
        "get_order_queue",
        "update_order_status",
        "get_reconciliation_report",
        "get_merchant_catchup",
        "get_inventory_alerts",
        "record_stock_adjustment",
        "list_support_cases",
        "reply_support_case",
    },
}


def environment() -> dict[str, str]:
    values = dict(os.environ)
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip("'\""))
    return values


def call(method: str, path: str, api_key: str) -> object:
    request = urllib.request.Request(
        BASE + path,
        headers={"Authorization": "Bearer " + api_key, "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            content = response.read()
    except urllib.error.HTTPError as exc:
        exc.read(500)
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path}: network error: {exc.reason}") from exc
    if not 200 <= status < 300:
        raise RuntimeError(f"{method} {path}: HTTP {status}")
    if not content:
        raise RuntimeError(f"{method} {path}: empty success response")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{method} {path}: non-JSON response") from exc


def items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "teammates", "mcp_servers"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                for nested_key in ("data", "results", "items"):
                    nested = value.get(nested_key)
                    if isinstance(nested, list):
                        return [item for item in nested if isinstance(item, dict)]
    return []


def unwrap(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    for key in ("data", "result", "teammate", "mcp_server"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return payload


def name(item: dict) -> str:
    value = item.get("name") or item.get("display_name")
    return value if isinstance(value, str) else ""


def mcp_ids(item: dict) -> list[str]:
    value = item.get("mcp_server_ids")
    return [str(entry) for entry in value] if isinstance(value, list) else []


def tool_names(payload: object) -> set[str]:
    if isinstance(payload, list):
        value: object = payload
    else:
        obj = unwrap(payload)
        value = obj.get("tools") or obj.get("items") or obj.get("data")
    if isinstance(value, dict):
        value = value.get("tools") or value.get("items")
    result: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                result.add(item)
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                result.add(item["name"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="also call Chord health and tool-discovery endpoints")
    args = parser.parse_args()
    env = environment()
    required = ("CHORD_API_KEY", "WORK_SPACE_ID", "TALLY_SHOP_ID", "TALLY_DESK_ID")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise RuntimeError("missing required environment keys: " + ", ".join(missing))

    api_key = env["CHORD_API_KEY"]
    workspace = env["WORK_SPACE_ID"]
    query = urllib.parse.urlencode({"workspace_id": workspace})
    teammates = items(call("GET", "/teammates?" + query, api_key))
    teammate_details: dict[str, dict] = {}
    for teammate in teammates:
        teammate_id = teammate.get("id")
        if not isinstance(teammate_id, str):
            continue
        teammate_details[name(teammate)] = unwrap(
            call("GET", "/teammates/" + urllib.parse.quote(teammate_id), api_key)
        )

    server_path = "/workspaces/" + urllib.parse.quote(workspace) + "/mcp-servers"
    servers = items(call("GET", server_path, api_key))
    server_by_name = {name(server): server for server in servers}
    shop_server = server_by_name.get("Tally Sandbox Shop", {})
    desk_server = server_by_name.get("Tally Sandbox Desk", {})
    sentinel = server_by_name.get("Chord Assistant MCP DENY (disabled)", {})
    shop = teammate_details.get("Tally Shop", {})
    desk = teammate_details.get("Tally Desk", {})
    assistant = teammate_details.get("Chord Assistant", {})

    checks = {
        "exact_teammate_count": len(teammate_details) == 3,
        "exact_server_count": len(servers) == 3,
        "shop_env_id_matches": shop.get("id") == env["TALLY_SHOP_ID"],
        "desk_env_id_matches": desk.get("id") == env["TALLY_DESK_ID"],
        "shop_only_shop_server": mcp_ids(shop) == [shop_server.get("id")],
        "desk_only_desk_server": mcp_ids(desk) == [desk_server.get("id")],
        "assistant_only_sentinel": mcp_ids(assistant) == [sentinel.get("id")],
        "sentinel_disabled": sentinel.get("enabled") is False,
        "no_empty_scopes": all(mcp_ids(item) for item in teammate_details.values()),
    }
    probes: dict[str, object] = {}
    if args.probe:
        for server_name, expected in EXPECTED_TOOLS.items():
            server = server_by_name.get(server_name, {})
            server_id = server.get("id")
            if not isinstance(server_id, str):
                probes[server_name] = {"error": "missing server"}
                checks[server_name + "_probe"] = False
                continue
            path = server_path + "/" + urllib.parse.quote(server_id)
            health = unwrap(call("POST", path + "/health", api_key))
            discovered = tool_names(call("POST", path + "/tools", api_key))
            ok = str(health.get("status", "")).lower() == "ok" and discovered == expected
            checks[server_name + "_probe"] = ok
            probes[server_name] = {
                "enabled": server.get("enabled"),
                "health": health.get("status"),
                "tool_count": len(discovered),
                "tools": sorted(discovered),
            }

    result = {
        "ok": all(checks.values()),
        "checks": checks,
        "teammates": {key: {"scope_count": len(mcp_ids(value))} for key, value in teammate_details.items()},
        "servers": {
            key: {
                "enabled": value.get("enabled"),
                "configured_tool_count": len(value.get("enabled_tools") or []),
            }
            for key, value in server_by_name.items()
        },
        "probes": probes,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(2)
