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
- Stock reservation, idempotent order creation, signed sandbox payment events (not customer-visible MCP), reconciliation report, merchant catch-up, low-stock alerts, order status and case-specific customer support.
- Automated tests (`pytest`) for identity isolation, payment mismatch/idempotency, out-of-stock and fulfilment failure scenarios.
- Default-off merchant connections: short-lived Paystack/Notion setup links, AES-GCM encrypted per-business credentials, Notion page-picker and bounded approval previews. With separate Admin approval, Tally creates a merchant-readable Notion workspace for Profile, Catalogue, Policies, Orders and Activity, then mirrors approved SQL records there; SQL remains authoritative. Paystack onboarding needs only a `transactions:write` restricted TEST key; webhook signing is optional. Orders can initialize hosted TEST checkout and customer claims are independently verified against Paystack before reconciliation. Manual-bank orders require audited Admin confirmation and remain separately labelled.

## Verification status — 6 November 2026

Independently observed:

- `tally.service` running one Uvicorn worker behind Nginx/TLS at `https://tally.mbrelabs.world`.
- Local and public `/healthz` responses report `status: ok` and `environment: sandbox`.
- `9 passed` before and after the live verification journey.
- Chord teammate isolation: Tally Shop has only the Shop MCP server; Tally Desk has only Desk; the native Chord Assistant has only a disabled deny server.
- Chord health and discovery: exactly 7 Shop tools and 11 Desk tools.
- Actual Chord-origin Shop and Desk tool invocations through persisted external-chat turns.
- Synthetic order `awaiting_payment` after a customer claim, `confirmed` only after a valid signed event, then fulfilled with correct stock accounting.
- Bad/missing/stale signatures, wrong amounts, unknown references, changed duplicate events, cross-customer access, Operator admin writes, unpaid dispatch, idempotency conflicts and sold-out orders fail safely.

Still pending for the assessment submission:

- Authenticated TSG Channel simulator UI capture and ≤3-minute recording.
- Native human takeover/delivery/hand-back proof.
- Evaluator-accessible Drive package and sent email receipt.

See `docs/DEPLOYMENT_FIELD_NOTES.md` for the evidence summary and honest limitations.

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

Sandbox only. No live merchant data, real WhatsApp numbers, production payment keys or channel-bound identity attestation. Chord API/external-chat tool calls were observed, but that does not substitute for the still-pending Channel simulator UI recording or native handoff proof. A stored support reply is not proof of customer delivery.

Provider code is disabled unless its explicit feature flag is enabled. Merchant Paystack credentials go only through the HTTPS form and are encrypted per business; Notion uses Tally's OAuth client and encrypted per-business tokens. Conversational registration, document approval, provider setup and Shop activation extend the existing tools without changing the seven-Shop/eleven-Desk counts. Source tests are not live-provider proof; see `docs/PROVIDER_CONNECTIONS.md` for activation gates.

`TALLY_SHOP_BOUND_SLUG` and `TALLY_SHOP_AGENT_URL` are deployment-level channel bindings, not merchant data defaults. One Shop agent instance must have one bound active business. Desk remains generic and can register other businesses, but each additional customer-facing Shop channel needs its own authenticated adapter binding before it is reachable.

## AI usage declaration

Architecture, skill instructions, documentation and backend source were generated and refined with ChatGPT (GPT-6). Codex subsequently performed live VPS, Chord API, tool-call and sandbox-ledger verification and prepared the submission documentation. Human review remains responsible for the final simulator recording, Drive sharing and email submission.
