# ASYAN SHOP — final implementation handoff and evidence boundary

**Refreshed 14 November 2026.** This is the up-to-date Codex/assessor entrypoint, superseding the earlier 37-test and undeployed-provider task list. No live keys, private actor IDs, setup URLs or user data belong in this file.

## Mission and architecture

Demonstrate **one business, ASYAN SHOP**, through one restricted Shop channel and one generic Desk teammate. Desk registers a clean empty tenant from the merchant's message. Merchant-authored CSV or independently existing Notion pages may be previewed and imported only with Admin approval; the Notion OAuth callback also creates/resumes Tally-owned readable workspace sections, which mirror already approved SQL records. Merchant owns their Paystack TEST account and provides a restricted key through a private HTTPS setup form. Shop creates a persisted order; only independent provider verification or signed sandbox test events can confirm payment; Desk reconciles and manages stock, fulfilment and support.

**Authoritative systems:** Paystack for Paystack payments, Tally SQL for orders/claims/inventory and audit, Notion for merchant-authored source material and authorized mirrors. Notion does not settle payments; chat text does not grant Admin rights.

## Latest implementation record

- 14 November source branch baseline: `8aedc3448ad3972fb290cd065be051a347aec758` (`Fix pickup-aware Shop order updates`). This SHA identifies the recorded **code baseline before documentation refresh**, not a final merged commit.
- Latest `docs/DEPLOYMENT_FIELD_NOTES.md` reports **62 tests passing in source and deployed checkout**, `git diff --check` clean, public/local health sandbox OK, SQLite integrity OK and authenticated Chord discovery **7 Shop / 11 Desk**.
- Merchant registration is genuinely prompt-driven and empty. The Shop cannot use a default Cedar tenant or switch to a different active business; this deployment binds `TALLY_SHOP_BOUND_SLUG` to ASYAN SHOP, with a stable `/shop/asyan-shop` entry only when active.
- The independent ASYAN SHOP Notion OAuth connection previously created five Tally-managed sections and backfilled three approved products plus an order; nine record/managed pages returned genuine Notion HTTP 200 reads on 13 November. Subsequent connection status and workspace status were also checked.
- A protected **14 November recording reset** retained merchant-authored ASYAN source pages but removed ASYAN registration, linked provider credentials and Tally-owned generated Notion pages. The public Shop route correctly returned HTTP 404 until reactivation. This is the known clean pre-recording state, **not necessarily the post-recording live state**.
- The existing Chord Shop/Desk skills were published in place as versions **16 and 18**, included and with no drafts. The 14 November pre-recording audit returned expected scopes; no subsequent chat/model turn is falsely inferred from that audit.
- Founder confirms **video recorded**. Exact video duration, public access, contents, final Paystack transaction reference and post-recording tenant state have not been inspected in this documentation pass. Do not claim the final E2E PASS without actual recording/trace review.

## Implemented technical behavior

| Area | Actual behavior / guard |
| --- | --- |
| Transport | HTTPS MCP at `/mcp/shop` and `/mcp/desk` with distinct bearer tokens, 7 and 11 tool allowlists, backend role enforcement. |
| Identity | Unverified simulator sender routing for assessment; never treat a typed phone number as real WhatsApp sender attestation. |
| Shop tenancy | Server-bound slug + active-business checks; customer-facing Shop is one merchant context, no selector. |
| Onboarding | Empty business creation, structured chat import, bounded CSV preview, Notion OAuth and explicit approval before merchant-authored data enters SQL. |
| Notion | Scoped OAuth, encrypted tokens, one-time state, five Tally-managed workspace sections, resumable/idempotent setup and SQL-to-Notion mirroring of approved records and operational changes. |
| Paystack | `rk_test_` with `transactions:write`, private one-use HTTPS setup session, encrypted business-specific connection, hosted TEST checkout, claim-triggered API verification. Webhook signing optional and business-scoped when configured; manual-bank confirmation separately audited. |
| Payment integrity | Claim remains unverified until provider check / independently signed sandbox event; reference, amount, NGN currency and merchant scope must match; replay-safe. |
| Fulfilment | Pickup: `confirmed → preparing → ready_for_pickup → fulfilled`; delivery: `confirmed → preparing → dispatched → delivery_reported → fulfilled`; customer confirmation or audited offline confirmation, stock deducted once. |
| Human support | Case record and Desk response are implemented. Native same-thread takeover, outbound delivery and hand-back remain separate channel-evidence requirements. |
| Reset | Explicit sandbox-only command backs up SQLite, deletes only recorded Tally-owned generated Notion pages to recoverable Trash and leaves merchant sources intact; fails safely on cleanup errors. |

## Reviewer / submission checklist

- [x] Source and deployed suite reported passing: 62 tests on 14 November; sandbox health, tool scopes and SQLite verified in field notes.
- [x] Genuine Notion OAuth write/readback verified on a previous ASYAN session; reset afterward for independent setup replay.
- [x] Recording **captured per founder**; verify final file, duration, sound, redaction and what it proves.
- [ ] Inspect final authenticated Desk and Shop simulator transcript and distinguish genuine Paystack TEST provider response from synthetic event or manual-bank confirmation.
- [ ] Verify final Notion source approval and final Orders write/readback in the recorded session; the earlier nine-page proof alone does not prove replay.
- [ ] Verify native same-thread human takeover/delivery/hand-back only if included or label unsupported.
- [ ] Add evaluator-accessible Drive URL and test file permissions without exposing tokens.
- [ ] Pin the merged Git SHA; include in submission index, Drive notes and email.
- [ ] Reply on existing TSG email thread with the Drive link, preferred role **Product**, and evidence boundary (founder instruction required before sending).

## Submission links

- Repository: https://github.com/Suqsuqx/tally-chord-reconciliation
- Final simulator script: `docs/ASYAN_SHOP_SIMULATOR_TEST_SCRIPT_2026-11-12.md`
- Technical verification: `docs/DEPLOYMENT_FIELD_NOTES.md`
- Product rationale: `docs/MVP_SCOPE_v1.2.md`
- Merchant-facing instructions: `docs/GO_LIVE_NOTE.md`
- Provider protocol / security: `docs/PROVIDER_CONNECTIONS.md`
- Evidence and URLs: `docs/SUBMISSION_LINK_INDEX.md`

No production WhatsApp identity, live payments or public merchant credential is implied. Do not submit without the founder's explicit go-ahead.
