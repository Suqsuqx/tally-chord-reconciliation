# Tally v1.2 — Chord reconciliation-first sandbox

Tally is a WhatsApp-first merchant operations assistant for the TSG Labs Chord Build Exercise. Two role-scoped Chord teammates and a small persistent MCP backend support this workflow:

**order → unverified payment claim → independently signed sandbox payment → merchant reconciliation/catch-up → fulfilment and stock exceptions**

This repository is an assessment sandbox, not a production payment or identity system.

## What is actually implemented

- Additive multi-tenant SQLite schema with conversational sandbox merchant registration, sender-to-business routing and tenant-scoped customers. A registration message creates a new empty business; approved business data and catalogue arrive afterward through chat, files or Notion.
- Tally starts with no runtime merchant, catalogue or customer-facing business identity. Shop requires an active merchant context; isolated tests create their own generic fixture outside runtime modules.
- Desk derives an arbitrary business name from the merchant's message and creates an empty private tenant. Each Shop MCP deployment is server-bound to exactly one configured slug, so its customer teammate cannot select or switch merchants.
- Successful activation returns a stable `/shop/{slug}` entry URL. That route exists only while the bound business is active and redirects to the configured customer channel (the TSG simulator for this assessment; a verified WhatsApp target in a live adapter).
- Shop and Desk JSON-RPC Streamable HTTP MCP endpoints with distinct bearer authentication and tool allowlists.
- Server-side Admin/Operator/Customer rules with legacy one-time codes plus explicit **unverified simulator sender routing**. The live contract remains authenticated WhatsApp-number identity; typed numbers are never authorization.
- Customer name and Paystack email memory scoped to the authenticated sender and merchant, stock reservation, idempotent order creation, signed sandbox payment events (not customer-visible MCP), reconciliation, low-stock alerts and case-specific support.
- Payment confirmation remains a hard fulfilment gate. Pickup-only orders use `confirmed → preparing → ready_for_pickup → fulfilled`; delivery orders use `confirmed → preparing → dispatched → delivery_reported → fulfilled`. Merchants may record offline progress, customer confirmation promotes a paid order to fulfilled, skipped stages are audited and stock is deducted exactly once. Customer status lookups return a concise, deterministic reply instead of requiring Shop to replay the whole order.
- Automated tests (`pytest`) for identity isolation, payment mismatch/idempotency, out-of-stock and fulfilment failure scenarios.
- Merchant connections use short-lived Paystack/Notion setup links and AES-GCM encrypted per-business credentials. Notion authorization creates or resumes five Tally-managed sections under the selected business page—Profile, Catalogue, Policies, Orders and Activity—and mirrors approved SQL records there. Merchant-authored source content remains previewed and imported only after Admin approval; SQL remains authoritative. A recording reset backs up SQLite, moves only Tally-owned Notion pages to Notion Trash, then clears the ledger. Paystack onboarding needs only a `transactions:write` restricted TEST key; webhook signing is optional. Paystack requires an email before checkout initialization, so Tally asks once and reuses it for that authenticated customer. The hosted page presents the merchant's enabled payment channels. Manual-bank orders require audited Admin confirmation and remain separately labelled.

## Verification and submission status — 14 November 2026

**Most recent technical evidence:** `docs/DEPLOYMENT_FIELD_NOTES.md` reports 62 passing tests on source and deployed checkouts, local/public health `status: ok` in sandbox mode, SQLite integrity OK, and an authenticated Chord scope audit confirming **7 Shop / 11 Desk tools**. The last 14 November code baseline before this documentation update is `8aedc3448ad3972fb290cd065be051a347aec758`.

**Merchant and provider proof:** The 13 November ASYAN SHOP session genuinely connected Tally's Notion OAuth integration, created five managed sections and read back nine generated pages via Notion's API. Provider setup reached connected status; the final Paystack TEST transaction and freshly repeated Notion import/order readback must be confirmed against the submitted recording and sanitized traces. The 14 November protected recording reset preserved merchant-authored ASYAN pages while removing Tally's generated pages, credentials and merchant ledger for a clean demo.

**Recording and submission:** The founder reports the final video **recorded**. This repository does not yet have a verified evaluator-facing video URL, playback inspection, Google Drive package, or sent email receipt. Native same-thread takeover and outbound message delivery should not be claimed without corresponding channel evidence.

**Technical boundaries:** The simulator sender is not authenticated WhatsApp ownership; payment claims are not settlement, and support-case replies are not delivery receipts. Tally refuses non-sandbox operation. Detailed product reasoning, merchant instructions, and provider security are documented in `docs/MVP_SCOPE_v1.2.md`, `docs/GO_LIVE_NOTE.md` and `docs/PROVIDER_CONNECTIONS.md`.

## Quick local start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env: replace placeholder secrets with three distinct long random values
set -a; . ./.env; set +a
.venv/bin/python -m pytest tests -q
.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8787
```

## Recording reset

To reset the sandbox after a recording pass, stop `tally.service`, load the private
environment, and run `scripts/reset_recording.py --execute --confirm "RESET TALLY RECORDING"`.
The script first creates a mode-`0600` SQLite backup, moves only pages recorded as
Tally-owned into Notion Trash, and replaces the SQLite ledger with the current empty
schema. The merchant-selected Notion parent and merchant-authored source pages remain.
If Notion cleanup fails, the database is left intact so the reset can be retried.

In another shell, run `scripts_utility.py issue-code cust-ada` and `scripts_utility.py issue-code staff-eni` to generate unique link codes, or use the tool demo through Chord after deployment.

The printed codes and returned tool sessions are short-lived secrets. Do not commit, record or paste them into public evidence. HTTPS is required for Chord's MCP client.

## Chord integration

Use the existing `Tally Shop` and `Tally Desk` teammates; do not create duplicates. Register distinct bearer-authenticated MCP servers for `/mcp/shop` and `/mcp/desk`, assign each teammate a nonempty singleton MCP scope, and keep the native Assistant restricted to a disabled credential-free sentinel. In Chord, an empty teammate scope means access to all enabled workspace MCP servers.

After configuration, run the read-only redacted audit:

```bash
set -a; . ./.env; set +a
.venv/bin/python scripts/chord_audit.py --probe
```

The script prints names, enabled state, scope checks, health and tool names; it never prints API keys, bearer tokens or session values.

## Scope and deployment

- `docs/MVP_SCOPE_v1.2.md`: updated scope and acceptance scenarios.
- `skills/tally-shop/SKILL.md`: Shop behavior and negative scenarios.
- `skills/tally-desk/SKILL.md`: reconciled catch-up and merchant operations.
- `docs/TOOL_REGISTER.md`: actual tools, roles and identity caveat.
- `docs/CHORD_KNOWLEDGE_DIAGNOSTIC.md`: diagnose the repeating library UI.
- `docs/CHORD_HANDOFF_VERIFICATION.md`: clarify native human takeover, case relay and timeout recovery.
- `docs/CHORD_SETUP.md`: MCP registration, tool permissions and simulator.
- `docs/DEPLOYMENT_FIELD_NOTES.md`: dated observed deployment and integration evidence.
- `docs/GO_LIVE_NOTE.md`: merchant-facing sandbox handoff and production blockers.
- `deploy/VPS_DEPLOY.md`: additive VPS install and security gates.

## Test/live boundary

Sandbox only. No live merchant data, real WhatsApp numbers, production payment keys or channel-bound identity attestation. Historical Chord API/external-chat tool calls are not substitutes for a Channel simulator recording. The founder reports that recording is now complete, but its individual events and any native human handoff still require playback/trace review. A stored support reply is not proof of customer delivery.

Provider code is disabled unless its explicit feature flag is enabled. Merchant Paystack credentials go only through the HTTPS form and are encrypted per business; Notion uses Tally's OAuth client and encrypted per-business tokens. Conversational registration, document approval, provider setup and Shop activation extend the existing tools without changing the seven-Shop/eleven-Desk counts. Source tests are not live-provider proof; see `docs/PROVIDER_CONNECTIONS.md` for activation gates.

`TALLY_SHOP_BOUND_SLUG` and `TALLY_SHOP_AGENT_URL` are deployment-level channel bindings, not merchant data defaults. One Shop agent instance must have one bound active business. Desk remains generic and can register other businesses, but each additional customer-facing Shop channel needs its own authenticated adapter binding before it is reachable.

## AI usage declaration

Architecture, skill instructions, documentation and backend source were generated and refined with ChatGPT (GPT-6). Codex subsequently performed live VPS, Chord API, tool-call and sandbox-ledger verification and prepared the submission documentation. Human review remains responsible for the final simulator recording, Drive sharing and email submission.
