# Connect the two Chord teammates after deploying the VPS host

**Do not create another teammate.** Use the existing Tally Shop and Tally Desk records.

**Observed 6 November 2026:** the live workspace required one corrective step before enablement because Shop and Desk were assigned to each other’s MCP server. After correction, fresh readback showed Shop→Shop, Desk→Desk and the native Assistant→disabled sentinel. Both operational servers then returned `health: ok`, exact tool discovery and successful Chord-origin tool calls. Always repeat the audit; do not assume this historical observation is current state.

## Skills

Upload/publish `skills/tally-shop/SKILL.md` to Shop, and `skills/tally-desk/SKILL.md` to Desk. Verify the correct file is marked **Instructions**, save/review/publish, and activate the teammates.

Configure each customer-facing Shop MCP deployment with exactly one server-side business binding. For the assessment instance, set `TALLY_SHOP_BOUND_SLUG` to the activated merchant slug and `TALLY_SHOP_AGENT_URL` to the HTTPS TSG simulator/channel entry. These values belong in private deployment configuration, not the skill, chat or merchant record. Desk stays generic and extracts the requested business name from each registration message. A second merchant must receive a separate authenticated Shop channel binding; customers must never select a store through Shop tool arguments.

## MCP

The two remote servers have intentionally different names, URLs and secrets:

- `Tally Sandbox Shop`: `https://YOUR_HOSTNAME/mcp/shop` — auth `bearer`, token `TALLY_SHOP_MCP_TOKEN`.
- `Tally Sandbox Desk`: `https://YOUR_HOSTNAME/mcp/desk` — auth `bearer`, token `TALLY_DESK_MCP_TOKEN`.

In Chord's workspace MCP settings, register each server initially disabled, then enable **only its tools**. Read and set each teammate's explicit `mcp_server_ids` before enabling any MCP server. **An unset or empty MCP server list means all enabled servers in Chord's documented behavior.**

For Shop permit: `link_identity`, `get_catalog`, `create_order`, `get_my_order`, `record_payment_claim`, `create_support_case`, `get_my_support_case`.

For Desk permit: `link_identity`, `get_catalog`, `upsert_product`, `get_order_queue`, `update_order_status`, `get_reconciliation_report`, `get_merchant_catchup`, `get_inventory_alerts`, `record_stock_adjustment`, `list_support_cases`, `reply_support_case`.

### Probe discovery

From your Chord key, use `POST /v1/workspaces/{workspace_id}/mcp-servers/{id}/tools` to discover tools, then `POST .../health` to check reachability (both requests with **no body**). An HTTP 200 health result with `status:error` is a failed probe. Finally run an ordinary simulator turn requiring an actual business tool call.

This repository includes `scripts/chord_audit.py --probe`, a read-only redacted audit for teammate assignments, sentinel state, health and exact tool discovery. It does not replace a simulator turn.

### Sandbox identity demo

Generate code on VPS from project root:

```bash
. .env
.venv/bin/python scripts_utility.py issue-code cust-ada
.venv/bin/python scripts_utility.py issue-code staff-eni
.venv/bin/python scripts_utility.py issue-code staff-tola
```

Share each test-only code with the intended simulated actor and redeem with the `link_identity` tool on the appropriate teammate. Codes are single-use; they expire after ten minutes. A linked session lasts two hours. The tool must keep its returned session token out of customer-visible chat. This demo scheme is **not cryptographically tied to the actual WhatsApp sender**; do not carry it to real production users.

## Payment event smoke test

After an order is created, invoke `scripts_utility.py sign-event BUSINESS_ID ORDER_ID AMOUNT_IN_KOBO` with `TALLY_WEBHOOK_SECRET` set. It prints timestamp, signature and raw JSON body. Deliver **exactly that body** to `/sandbox/provider-event` with headers `X-Tally-Timestamp`, `X-Tally-Signature` and `Content-Type: application/json`. Do not put webhook secrets in Chord tools or chats. A mismatched event should remain an exception.

## Channel

Visit https://chat.tsglabs.dev/ and use the Chord Chat simulator after enabling Allowed Apps / channel access in the workspace. Set up a separate chat link for each teammate and test Shop and Desk without real phone numbers. Native handover must be tested on Shop's actual channel conversation, not inferred from in-app replies.

Docs: https://api.chordhq.xyz/docs/build-a-teammate/ ; https://api.chordhq.xyz/docs/mcp-servers/
