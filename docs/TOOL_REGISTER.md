# Tally tool register (implemented in sandbox server)

Each tool is exposed through **one** of two authenticated public HTTPS endpoints. All arguments below must be supplied through tool schemas. Business authorization is checked server-side, not by the prompt.

## Customer — `/mcp/shop`

| Tool | Private? | Outcome |
|---|---:|---|
| `link_identity` | Shop context | Route an unverified simulator sender to an active merchant slug (legacy codes remain for regression tests). |
| `get_catalog` | Public/session | Tenant-scoped approved profile/policies, products, prices and availability. |
| `create_order` | Customer session | Recheck stock, reserve units and return manual-bank instructions or initialize Paystack TEST checkout idempotently. |
| `get_my_order` | Customer session | Customer-owned order and status only. |
| `record_payment_claim` | Customer session | Record the claim, then independently verify a mapped Paystack transaction; otherwise remain unverified. |
| `create_support_case` | Customer session | Persist inquiry/complaint with owner and optional own order. |
| `get_my_support_case` | Customer session | Read own case and recorded replies. |

## Merchant — `/mcp/desk`

| Tool | Permission | Outcome |
|---|---|---|
| `link_identity` | Sandbox sender/business context | Register/resume merchant Admin, save approved onboarding data/payment choice and activate only when ready. |
| `get_catalog` | Both | Merchant catalogue/onboarding state, authorized Notion resources and optional bounded preview. |
| `upsert_product` | Admin | Add or change price, physical stock and threshold. |
| `get_order_queue` | Both | All current orders for sandbox business. |
| `update_order_status` | Both/Admin confirmation | Paid fulfilment transitions; Admin-only audited manual-bank confirmation from awaiting payment. |
| `get_reconciliation_report` | Both | Verified matched payments, exceptions, unpaid orders and claims. |
| `get_merchant_catchup` | Both | Time-scoped activity + report + stock and support backlog. |
| `get_inventory_alerts` | Both | Low/out of stock alerts, accounting for reserved stock. |
| `record_stock_adjustment` | Admin | Logged physical-stock adjustment. |
| `list_support_cases` | Both | Support queue. |
| `reply_support_case` | Both | Case-scoped recorded merchant response, delivery not presumed. |

When a sandbox Admin registers or resumes through `link_identity` and a provider feature is enabled, the result includes short-lived private setup links. Operators never receive them. The same seven/eleven tool counts are preserved.

## Provider-only, not an MCP tool

`POST /sandbox/provider-event` validates HMAC-SHA256 of `{timestamp}.{raw body}` and rejects timestamps outside five minutes. It accepts `event_id`, `reference` (order ID), `amount_minor`, `currency=NGN`, `event_status=success`. Replays with the same `event_id` are idempotent. A verified provider event with mismatched data is recorded as an exception, **not** matched to the order. Tool registration credentials cannot access it without the separate provider signing secret.

## Identity gate to verify on Chord

The sandbox accepts an explicit simulator sender identifier only to demonstrate routing and repeats `identity_assurance=unverified_simulator`. It is not authentication. The live WhatsApp adapter must derive the sender number from the authenticated provider envelope and inject it server-side; it must never authorize a phone number typed in message text.

## MCP transport note

This project implements stateless JSON-RPC `initialize`, `ping`, `tools/list` and `tools/call` over Streamable HTTP. On 6 November 2026, Chord health and discovery returned exactly seven Shop and eleven Desk tools, and persisted Chord external-chat turns successfully invoked both servers. The provider branch keeps those counts unchanged, but has not yet been deployed or re-probed through Chord. Authenticated TSG Channel simulator UI capture remains a separate acceptance gate.
