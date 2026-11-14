# Tally tool register (implemented in sandbox server)

Each tool is exposed through **one** of two authenticated public HTTPS endpoints. All arguments below must be supplied through tool schemas. Business authorization is checked server-side, not by the prompt.

## Customer — `/mcp/shop`

| Tool | Private? | Outcome |
|---|---:|---|
| `link_identity` | Server-bound Shop context | Route a sender to the one active bound business, remember customer-provided name/email and return pending delivery confirmations. Merchant selection is not exposed. |
| `get_catalog` | Bound active Shop/session | Tenant-scoped approved profile/policies, products, prices and availability. The server injects the binding; there is no Tally-wide catalogue or store selector. |
| `create_order` | Customer session | Recheck stock, reserve units and automatically use the merchant's configured manual-bank or Paystack method. Reuse a remembered Paystack email when available. |
| `get_my_order` | Customer session | Read only the customer's order and provide one concise status reply; explicit receipt/pickup confirmation promotes a paid order to fulfilled and resolves the matching confirmation request. |
| `record_payment_claim` | Customer session | Record the claim, then independently verify a mapped Paystack transaction; otherwise remain unverified. |
| `create_support_case` | Customer session | Persist inquiry/complaint with owner and optional own order; a delivery mismatch remains unfulfilled and is flagged to Desk. |
| `get_my_support_case` | Customer session | Read own case and recorded replies. |

## Merchant — `/mcp/desk`

| Tool | Permission | Outcome |
|---|---|---|
| `link_identity` | Sandbox sender/business context | Register/resume merchant Admin, save approved onboarding data/payment choice and activate only when ready. |
| `get_catalog` | Both | Merchant catalogue/onboarding state, authorized Notion resources and optional bounded preview. |
| `upsert_product` | Admin | Add or change price, physical stock and threshold. |
| `get_order_queue` | Both | All current orders for sandbox business. |
| `update_order_status` | Both/Admin confirmation | Record forward paid progress, including pickup readiness (`ready_for_pickup`) or delivery reports and offline stage jumps; Admin-only audited manual-bank confirmation from awaiting payment. |
| `get_reconciliation_report` | Both | Verified matched payments, exceptions, unpaid orders and claims. |
| `get_merchant_catchup` | Both | Time-scoped activity + report + stock and support backlog. |
| `get_inventory_alerts` | Both | Low/out of stock alerts, accounting for reserved stock. |
| `record_stock_adjustment` | Admin | Logged physical-stock adjustment. |
| `list_support_cases` | Both | Support queue. |
| `reply_support_case` | Both | Case-scoped recorded merchant response, delivery not presumed. |

When a sandbox Admin registers or resumes through `link_identity` and a provider feature is enabled, the result includes short-lived private setup links. Operators never receive them. The same seven/eleven tool counts are preserved.

When activation succeeds, the Desk result includes `shop_access.status`, `shop_access.shop_slug` and a stable `shop_access.entry_url` derived from `TALLY_PUBLIC_BASE_URL`. `GET /shop/{slug}` redirects to `TALLY_SHOP_AGENT_URL` only when the requested slug matches this deployment's `TALLY_SHOP_BOUND_SLUG` and that business is active. Inactive, missing or different businesses remain unavailable.

## Provider-only, not an MCP tool

`POST /sandbox/provider-event` validates HMAC-SHA256 of `{timestamp}.{raw body}` and rejects timestamps outside five minutes. It accepts an explicit `business_id`, `event_id`, `reference` (order ID), `amount_minor`, `currency=NGN`, and `event_status=success`. It never falls back to a demo tenant. Replays with the same `event_id` are idempotent. A verified provider event with mismatched data is recorded as an exception, **not** matched to the order. Tool registration credentials cannot access it without the separate provider signing secret.

## Identity gate to verify on Chord

The sandbox accepts an explicit simulator sender identifier only to demonstrate routing and repeats `identity_assurance=unverified_simulator`. It is not authentication. The live WhatsApp adapter must derive the sender number from the authenticated provider envelope and inject it server-side; it must never authorize a phone number typed in message text.

## MCP transport note

This project implements stateless JSON-RPC `initialize`, `ping`, `tools/list` and `tools/call` over Streamable HTTP. The 14 November 2026 field notes report the source deployed on the VPS, and a redacted authenticated Chord audit confirmed exactly seven Shop and eleven Desk tools with the existing teammates and disabled Assistant sentinel. The founder reports a final Channel simulator recording has been captured; playback and individual conversation traces have not been inspected by this documentation update. See the dated evidence and boundaries in `docs/DEPLOYMENT_FIELD_NOTES.md`.
