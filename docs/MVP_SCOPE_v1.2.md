# Tally — Reconciliation-First MVP Scope

**Project:** TSG Labs Chord Build Exercise  
**Version:** 1.2 · 5 November 2026  
**Status:** Sandbox backend, VPS HTTPS service, Chord MCP health/discovery, real Chord-origin Shop/Desk tool calls, signed-payment journey and security failures verified on 6 November 2026. Authenticated Channel simulator UI evidence and native handoff remain pending.

## 1. Purpose and success definition

Tally is a WhatsApp-first business operations assistant that keeps merchant orders, payment reports, fulfilment and stock records in sync and explains what needs attention. The main product interaction is the merchant asking, *“What's happened, what doesn't add up, and what should I do next?”* Tally responds with a reconciled business catch-up grounded in stored records—not an invented narrative.

**MVP proof:** in TSG Labs' Chord WhatsApp simulator, a customer places an order; their payment report stays unverified; an authenticated sandbox payment event is matched against the order; the merchant retrieves the reconciliation result, catches up on orders and support, and sees a low-stock alert. Failures must be handled safely and demonstrably.

## 2. Experience, actors and permissions

Two separately configured Chord teammates work with sandbox merchants in one multi-tenant database and explicit tool scopes. A merchant is created conversationally; runtime code contains no default merchant or catalogue.

| Teammate / actor | Purpose and accessible operations |
|---|---|
| **Tally Shop / Customer** | Browse current catalogue, place own order, report payment claim, check own order, open complaint or inquiry, read response in own case. Cannot read merchant-wide or other-customer records. |
| **Tally Desk / Admin** | Add/edit catalogue prices, stock and alert thresholds; inspect all business orders, reconciliation, catch-up, stock warnings and support queue; reply to cases; progress fulfilment; record inventory adjustments. |
| **Tally Desk / Operator** | Inspect relevant business orders, reports and support queue; reply to cases; progress verified-paid fulfilment. Cannot change catalogue prices, adjust stock quantities, approve payments or manage business membership. |

Multiple individual staff may hold Admin or Operator roles. Business membership, actor identity and access are checked by Tally's backend for every private tool call. **The Chord teammate role, prompt instructions, and possession of a chat link do not establish user authorization.**

**Assessment identity implementation:** single-use expiring sandbox access codes issued by a server-side administrator link each *test actor* to a temporary tool session. Separate shop and desk MCP credentials protect the tool surfaces. These codes prove authorization within the controlled test, **not ownership of a real WhatsApp number**. A live channel requires a separately verified, provider-signed actor binding before customer deployment.

## 3. Merchant setup and catalogue

The assessment begins when the merchant messages Tally Desk to register a business. That message creates an empty tenant and assigns the current simulator sender as its sandbox Admin; it does not claim or copy a pre-registered business. The Admin then supplies business details and catalogue through conversation, uploaded files or authorized Notion documents. Tally previews names, prices, stock counts and warning thresholds before approved writes. An empty authorized Notion parent can also become a merchant-readable Tally workspace with Profile, Catalogue, Policies & FAQ, Orders, and Activity & Reconciliation sections. SQL remains authoritative and approved records are mirrored to Notion. The API accepts NGN amounts as integer **kobo** and calculates available quantity as physical stock on hand minus units reserved on existing orders. The customer agent reads the same persisted catalogue, and order creation rechecks availability transactionally.

Desk is business-name agnostic: it derives the exact requested name and creates that tenant. A customer-facing Shop instance is not a marketplace. Its MCP deployment is bound server-side to one activated business, exposes no merchant selector, and returns a stable entry URL after activation. The assessment Shop binding points to the single simulator agent; a live adapter would bind an equivalent business-specific link or verified WhatsApp route.

## 4. Customer order and payment reconciliation

1. Tally Shop reads current product availability and confirms requested quantities and total with the customer.
2. `create_order` rechecks stock, calculates prices from the database, reserves units and returns one persisted order reference. Idempotency keys prevent duplicate orders; a reused key with different items is rejected.
3. The order starts as `awaiting_payment`. A transfer message or screenshot is recorded only by `record_payment_claim` and **does not** confirm an order.
4. A separate sandbox provider endpoint accepts a successful signed payment event with event ID, reference, amount and currency. The backend validates its signature and freshness, matches the reference/amount/currency, and deduplicates the event ID.
5. A matching valid event moves the order to `confirmed`; an unknown reference, mismatch or already processed order remains an exception in the payment report. A duplicate event has no second settlement effect.
6. The Admin or Operator progresses the order: `confirmed` → `preparing` → `dispatched` → `fulfilled`. Unpaid dispatch is rejected. Stock is reserved on order creation and deducted from on-hand quantities at fulfilment.

**Reconciliation report:** total matched verified receipts; count and amount of unpaid orders; unresolved customer payment claims; unmatched references, amount mismatches and duplicate-safe event outcomes. Money values are computed by tools and clearly distinguish verified receipts from unpaid expectations and claims.

## 5. Merchant catch-up, inventory and exceptions

Tally Desk answers conversational requests like *“Catch me up since this morning”* by calling `get_merchant_catchup` with a time boundary. Its report combines recent order/payment activity, payment exceptions, active support cases, recent staff actions and inventory changes. The default window is the previous 24 hours. Reconciliation and stock alerts come from separate deterministic tool outputs; Tally prioritizes material exceptions without guessing their causes.

Inventory alerts compare available quantity against a configured threshold. Admins can record physical-count adjustments with a reason and audit record; those adjustments do not imply Tally independently observed physical stock. Warnings include sold-out and low-stock quantities.

## 6. Customer service, assisted replies and handoff

Tally Shop answers routine enquiries using tool results and published merchant policy. For complaints, uncertainty, delivery exceptions or requests requiring merchant judgment, the agent should **initiate help**, rather than merely tell the customer to find a person:

- Create a case with the customer's authenticated actor and optional own order.
- Acknowledge naturally, show the case reference, and give the customer a concrete next step without inventing a resolution.
- Present the case in Tally Desk's merchant queue. An Operator or Admin replies through `reply_support_case`; that response belongs to this customer's case, not a shared FAQ.
- Prefer native Chord `handover_to_human` when supported by the simulator/channel and staff availability; a human can then take over the **same customer thread**, reply directly and hand control back. **This is distinct from the merchant answering a case in Tally Desk.**
- Test outbound notification of a case response and record its provider/channel delivery result if supported. If not confirmed, the customer can retrieve the approved response through `get_my_support_case`. A saved message is not evidence of delivery.

**Recovery:** an open support case waiting more than ten minutes is shown as overdue in merchant catch-up. Native human takeover, hand-back and delivery status should be tested in Chord. We do not silently transfer a human-owned conversation back to the agent simply because its operator is idle; automatic reminders/reassignment require verified event delivery and explicit policy.

**Knowledge separation:** Chord Knowledge holds approved, general merchant policies; the Tally database holds private orders and individual support records. A staff answer is not promoted into reusable business knowledge automatically. Chord's user memory is not the shared source of merchant truth.

## 7. Technical scope and interfaces

| Component | Responsibility |
|---|---|
| **Chord Tally Shop** | Customer conversation and sandbox-linked customer-only tools; may request native handoff. |
| **Chord Tally Desk** | Admin/Operator conversation and approved merchant tools; staff actions audited individually. |
| **VPS Tally service** | Stateless Streamable HTTP MCP endpoints `/mcp/shop` and `/mcp/desk`, each with distinct bearer credentials and tool lists; business rules and role checks. |
| **Sandbox SQLite database** | Products, actors, temporary test sessions, orders, reserved stock, payment claims/events, case messages, adjustments and audit. |
| **Sandbox payment adapter** | Signed, timestamped `POST /sandbox/provider-event`; never exposed to a Chord teammate as a payment-confirmation tool. |
| **Chord Knowledge** | Business-approved help/runbooks, attached to their intended teammates; never live stock or account ledger. |
| **TSG Channel simulator** | Simulated WhatsApp conversation and, where supported, human takeover and return delivery. |

Tools currently implemented in the local code are named in `docs/TOOL_REGISTER.md`. Chord tool discovery and deployment are separate acceptance gates. The server intentionally refuses non-sandbox operation; no production payment provider or WhatsApp ownership verification is claimed.

## 8. Acceptance criteria

| ID | Scenario | Passing evidence |
|---|---|---|
| **A1** | Merchant adds/updates catalogue | Authorized Admin tool write persists; Shop retrieves current data; Operator price edit denied. |
| **A2** | Customer order | Availability checked; accurate total and reference; duplicate request id does not create another order. |
| **F1** | Out of stock | Order rejected; no order persisted; customer receives a natural availability explanation. |
| **A3** | Payment reconciliation | Customer claim leaves order unpaid; signed matching event confirms once; merchant report reflects matched verified receipt. |
| **F2** | Payment anomaly | Bad signature, wrong amount, unknown reference and duplicate event do not falsely confirm or double-count a payment. |
| **A4** | Fulfilment and stock | Unpaid dispatch rejected; valid paid transitions succeed; reserved/physical quantity and low-stock alert are correct. |
| **A5** | Merchant catch-up | Desk returns recent activity and actionable reconciliation, support and stock exceptions from tools. |
| **A6** | Customer service | Customer complaint creates a merchant-visible case; staff response is stored; customer retrieves that response only from their own case. |
| **V1** | Native human handoff | In simulator, verify takeover, direct human reply, channel delivery and hand-back where supported; log any unsupported link accurately. |
| **F3** | Authorization | Second customer cannot read first customer's order/case; Shop cannot invoke merchant MCP tools; Operator cannot adjust prices/stock. |
| **V2** | Knowledge persistence | Bundle exists, file is indexed, teammate has access, and an answer demonstrates retrieval; document any Chord UI failure separately. |

## 9. Submission artifacts

Two published Chord teammates with separate skill packages; running HTTPS MCP backend on the VPS; Chord simulator conversation and tool trace; GitHub repository containing skill and source code, tests and README; three-minute recording showing an actual reconciliation action; field notes on real failures and fixes; and a short merchant go-live handoff. Only events actually observed should be described as proven.
