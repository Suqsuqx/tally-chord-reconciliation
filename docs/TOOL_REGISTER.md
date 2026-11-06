# Tally tool register (implemented in sandbox server)

Each tool is exposed through **one** of two authenticated public HTTPS endpoints. All arguments below must be supplied through tool schemas. Business authorization is checked server-side, not by the prompt.

## Customer — `/mcp/shop`

| Tool | Private? | Outcome |
|---|---:|---|
| `link_identity` | Redeem sandbox code | Short-lived test customer session. Never echo token. |
| `get_catalog` | Public | Current product name, price in kobo, available quantity. |
| `create_order` | Customer session | Recheck stock, reserve units, persist order and total, idempotent request. |
| `get_my_order` | Customer session | Customer-owned order and status only. |
| `record_payment_claim` | Customer session | Unverified claim; never settles an order. |
| `create_support_case` | Customer session | Persist inquiry/complaint with owner and optional own order. |
| `get_my_support_case` | Customer session | Read own case and recorded replies. |

## Merchant — `/mcp/desk`

| Tool | Permission | Outcome |
|---|---|---|
| `link_identity` | Redeem sandbox staff code | Short-lived Admin or Operator test session. |
| `get_catalog` | Both | Merchant catalogue and available quantity. |
| `upsert_product` | Admin | Add or change price, physical stock and threshold. |
| `get_order_queue` | Both | All current orders for sandbox business. |
| `update_order_status` | Both | Valid paid-order fulfilment transition. |
| `get_reconciliation_report` | Both | Verified matched payments, exceptions, unpaid orders and claims. |
| `get_merchant_catchup` | Both | Time-scoped activity + report + stock and support backlog. |
| `get_inventory_alerts` | Both | Low/out of stock alerts, accounting for reserved stock. |
| `record_stock_adjustment` | Admin | Logged physical-stock adjustment. |
| `list_support_cases` | Both | Support queue. |
| `reply_support_case` | Both | Case-scoped recorded merchant response, delivery not presumed. |

## Provider-only, not an MCP tool

`POST /sandbox/provider-event` validates HMAC-SHA256 of `{timestamp}.{raw body}` and rejects timestamps outside five minutes. It accepts `event_id`, `reference` (order ID), `amount_minor`, `currency=NGN`, `event_status=success`. Replays with the same `event_id` are idempotent. A verified provider event with mismatched data is recorded as an exception, **not** matched to the order. Tool registration credentials cannot access it without the separate provider signing secret.

## Identity gate to verify on Chord

The backend now distinguishes individual test Admin/Operator/Customer sessions. **Chord's documented static MCP bearer credential alone does not identify a WhatsApp sender.** The sandbox uses one-time actor codes and short-lived tool session tokens. Before serving real customers, verify whether the connected channel can supply a signed identity claim to the MCP server; otherwise build a secure out-of-band channel binding. Do not interpret a demonstration code as real-world phone verification.

## MCP transport note

This project implements stateless JSON-RPC `initialize`, `ping`, `tools/list` and `tools/call` over Streamable HTTP. On 6 November 2026, Chord health and discovery returned exactly seven Shop and eleven Desk tools, and persisted Chord external-chat turns successfully invoked both servers. Authenticated TSG Channel simulator UI capture remains a separate acceptance gate.
