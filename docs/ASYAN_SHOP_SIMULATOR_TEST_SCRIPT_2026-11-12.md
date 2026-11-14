# Tally — ASYAN SHOP TSG Simulator Acceptance Script
**Prepared:** 12 November 2026 · **Target:** one dedicated Tally Desk + one ASYAN SHOP Tally Shop · **Mode:** sandbox/test only

## Scope, evidence and safety
This is a **human-executed conversation script**, not evidence that any step succeeded. Execute in the authenticated [TSG Channel Simulator](https://chat.tsglabs.dev/), save message timestamps, tool steps (name/result), backend order/case IDs and sanitized screenshots. Mark each gate PASS, FAIL or BLOCKED. Do not reproduce expected sample replies as actual agent answers.

Latest GitHub issue update: 39 tests reported passing; latest deployed service/Chord scopes healthy (Shop 7/Desk 11). **ASYAN SHOP has been deliberately reset to unregistered** for a fresh onboarding test. Merchant Paystack key and Notion OAuth still need real merchant authorization. The merchant's independently created [Notion workspace](https://app.notion.com/p/415f0bb831ad81f78d10d3d621ac1fd9) currently has an empty Orders database and a three-product catalogue. Do not pre-import or pre-authorize it.

**Sensitive material:** No `rk_test_`, `sk_test_`, `whsec_`, private setup URL fragments, Chord credentials, Notion OAuth tokens, sandbox identity codes or session tokens in GitHub, recordings or public evidence. Submit test credentials only via the intended secure HTTPS provider form. The simulator's sender value is unverified; do not describe it as a real verified WhatsApp identity. Do not use real purchases or private customer data.

## Preflight (operator, not a chat prompt)
- Confirm `https://tally.mbrelabs.world/healthz` responds `status:ok, environment:sandbox`.
- On the VPS, privately: back up DB; verify deployed commit, run `.venv/bin/python -m pytest tests -q` (latest reported count **39**, not a guarantee), and `.venv/bin/python scripts/chord_audit.py --probe`.
- Verify **existing** Chord Tally Desk has only Desk MCP tools (11), Tally Shop only Shop MCP tools (7), and native Assistant points only to disabled sentinel. Do not create duplicate teammates or expand permissions.
- Confirm TSG Connected Apps approval, authenticated separate simulator chat links for Desk and Shop; record the test session IDs privately. Ensure the ASYAN SHOP database row/slug is genuinely absent and any prior ASYAN Shop context is not cached, without clearing historical Cedar orders.
- Keep Notion Catalogue intact; Notion Orders is empty at the start. Do not access merchant Notion via ChatGPT in the Tally demo or pre-populate SQL.

## A. Tally Desk — merchant creation and initial context (start recording evidence)
**A1 — First message, fresh Desk thread**

Merchant types:
> Hi Tally, I want to set up my bakery, ASYAN SHOP, in Lagos. Can you register it? I already have business records and a Paystack account. Please don't create or import a catalogue until I approve what you find.

Expected: Desk calls `link_identity` with a new test simulator sender context and `business_name=ASYAN SHOP`. Result indicates `registration_status=created`, role Admin and an **empty** product catalogue/onboarding state. It offers chat/CSV/Notion methods and, if enabled, secure Paystack and Notion setup links. Save business ID and slug returned (expected slug `asyan-shop`; confirm actual tool result). **No recurring OTP** is expected in the intended experience.

**A2 — Separate-turn continuity and non-fabrication**

Merchant types in a *new message*:
> What do you currently know about ASYAN SHOP? What products and payment connections are actually configured? Don't guess or use my Notion records until I authorize them.

Expected: Desk uses the persisted Admin context to read actual onboarding state. Empty catalogue and unconnected integrations must not be presented as complete. If Desk asks for login/code again, record **FAIL: multi-turn identity continuity** rather than quietly skipping.

## B. Tally Desk — independent Notion and Paystack connections
**B1 — Notion OAuth**

Merchant:
> Connect my existing Notion workspace. I want to grant you access to my ASYAN SHOP pages, then preview what you find before importing anything.

Expected: Desk displays only the genuine Tally-generated **short-lived secure Notion setup link**. Open it privately, authorize Tally's own Notion OAuth application, and select the merchant's ASYAN SHOP workspace plus appropriate child pages/data sources. Return to Desk:

> Which business documents did I share? Show me a preview of the profile, product catalogue and customer FAQs. Do not import until I confirm.

Expected: actual authorized resource IDs and contents; three products and prices from Notion (chocolate cupcake ₦2,500 stock 14; vanilla cupcake ₦2,000 stock 0; brownie box ₦6,500 stock 5). **No pre-existing connection claim**. Review the mapping and explicitly say:

> I approve importing those three catalogue products and the customer-facing information you showed me into ASYAN SHOP.

Expected: SQL-backed records now populated with correct kobo conversion (250000, 200000, 650000); read back with Desk `get_catalog`. If only preview exists and a manual `upsert_product` is required, use Admin-approved fallback but mark **automated Notion import = BLOCKED/FAIL**; do not pretend it occurred.

**B2 — Paystack restricted TEST key**

Merchant:
> Connect my existing ASYAN SHOP Paystack account for customer checkout, using test mode. Give me the secure connection link.

Expected: genuine short-lived HTTPS form URL from Desk, not a request to paste a key into WhatsApp. Privately enter the `rk_test_` restricted key in Tally's form. Backend checks the account and transaction API access, stores encrypted per-business credentials. Optional webhook setup only if genuinely needed; claim-triggered server-side API verification can be the acceptance path. Ask Desk:

> Is ASYAN SHOP's Paystack test connection genuinely verified? Please tell me whether customer checkout is ready.

Expected: response grounded in actual provider verification. If the provider rejects permissions or a connection is missing, stop and log **BLOCKED**, not "connected".

**B3 — Shop activation**

Merchant:
> The catalogue and customer policies are approved, and Paystack is connected. Please activate ASYAN SHOP's customer Shop and give me its test link.

Expected: Shop transitions to active only after readiness checks. Keep a distinct dedicated ASYAN SHOP Shop link. No new business/agent factory or multi-tenant directory is required in this assessment.

## C. Tally Shop — customer journey (new customer thread)
**C1 — Catalogue, availability, policy**

Customer:
> Hi, is this ASYAN SHOP? What can I buy today, and do you deliver in Lagos?

Expected: Shop recognizes its fixed merchant context; obtains SQL-backed catalogue/policies, accurately describes what is available and says delivery charge/ETA must be confirmed, not invented.

Customer:
> I'll take one vanilla cupcake.

Expected: `OUT_OF_STOCK` / quantity zero; no persisted order, no checkout. Offer only verified available alternatives.

**C2 — Order and unverified claim**

Customer:
> Okay, two chocolate cupcakes instead. What's the total?

Expected: ₦5,000. Shop should confirm basket and quantity and ask whether to proceed.

Customer:
> Yes, place the order. For the test checkout, use [TEST_EMAIL].

Expected: Shop uses `create_order` with stable request_id, reserves two cupcakes, returns one actual `TLY-...` order reference and a genuine Paystack TEST checkout URL or explicitly reports unavailable. Record the real reference as `ORDER_ID`, amount = `500000` kobo. Do not claim paid merely because checkout started.

**Before completing test checkout**, customer:
> I just paid for ORDER_ID. Can you confirm it?

Expected: Shop calls `record_payment_claim`; **order remains awaiting_payment and verified=false** unless an independently verified actual provider transaction already exists.

**Complete a real Paystack TEST checkout** through the provider's authorized test UI, then customer:
> Please check the payment for ORDER_ID again. What's the verified status?

Expected: only provider-confirmed status can be labelled paid; `verification_source=paystack_api` when claim-triggered verification succeeds. Record external test transaction reference (sanitized). If provider has not confirmed, keep pending—don't force an outcome.

Customer:
> What's the current status of ORDER_ID?

Expected: `get_my_order` reports the actual SQL state for this customer, not another user's order.

## D. Tally Desk — reconciliation, fulfilment, support
**D1 — Same original Desk conversation, separate turns**

Merchant:
> I'm back. Catch me up on today's ASYAN SHOP orders, verified payments, unpaid claims, stock warnings and anything that needs attention.

Expected: Desk recognizes same Admin without a second OTP, uses `get_merchant_catchup`, `get_reconciliation_report`, and `get_inventory_alerts`, and distinguishes Paystack verification from customer claims. Capture actual counts and discrepancies.

Merchant:
> Show me ORDER_ID. If Paystack verified it, mark it preparing, then dispatched, then fulfilled, one step at a time.

Expected: no unpaid dispatch. For a verified order, `confirmed → preparing → dispatched → fulfilled`; cupcake on-hand decreases by 2 when fulfilled (initial 14 → 12 if no other test orders; reserved becomes 0). If not verified, **do not** progress; stop and report payment blocker.

**D2 — Case relay**

Back in Shop, customer:
> My cupcakes arrived damaged. Can someone at the shop help with ORDER_ID?

Expected: `create_support_case`, returns real `CASE_ID`; case belongs to this customer. Acknowledge escalation without claiming human takeover/delivery.

Desk merchant:
> Show me unresolved customer issues. For CASE_ID, reply: "We're sorry. We'll review the order and contact you about a replacement."

Expected: `list_support_cases` then `reply_support_case`. The reply is **recorded**, with customer delivery **not yet verified** unless native channel evidence exists.

Back in Shop:
> What did the shop say about CASE_ID?

Expected: `get_my_support_case` shows exact stored staff reply.

**D3 — Notion bidirectional proof**

Merchant:
> Show me the order record that Tally saved back to my authorized ASYAN SHOP Notion workspace. Confirm by reading it back, with the same order reference and payment status.

Expected: Notion permissioned **write AND readback** with corresponding SQL order reference. The source merchant Orders database is initially empty; if code instead writes into a newly created child page/section rather than the merchant's original Orders database, describe exactly where it wrote and label the original Orders database sync **not proven**. A Notion status never settles Paystack.

## E. Negative/security cases (separate from short video)
- Different simulated customer requests `ORDER_ID` or `CASE_ID` → `NOT_FOUND`/denied; no private data.
- Shop asks for merchant-wide receipts or stock editing → denied/unavailable.
- Admin tries to dispatch an unpaid test order → rejected without state mutation.
- Operator attempts Admin-only price/stock change → `FORBIDDEN` (if Operator invitation implemented; otherwise document missing).
- Bad Paystack signature, wrong amount/currency/reference, provider replay and duplicate order request IDs → reject, record exception or deduplicate; never falsely mark paid.
- Change Desk context or reopen a fresh conversation; if a second login is required for normal Admin review, record FAIL and the exact trace.
- Test native handover only if the TSG simulator supports actual customer-thread takeover, human delivery and hand-back. A Desk support reply is **not** native handoff proof.

## F. Recording and evidence ledger
For each milestone record: test actor, exact message timestamp, tool name/result, business ID, `ORDER_ID`, `CASE_ID`, actual expected vs observed, PASS/FAIL/BLOCKED, screenshot/transcript link, backend log IDs (sanitized), and any provider/Notion record identifiers. Do not paste full setup links, API secrets or access tokens.

Suggested **≤3-minute editorial cut** (internal target; do not invent missing successes):
- 0:00–0:30 — ASYAN SHOP signup, empty business + private merchant Desk.
- 0:30–1:05 — real Notion consent/preview and secure Paystack connection, only if those passes exist.
- 1:05–1:50 — customer catalogue, sold-out handling, order, claim vs verified payment.
- 1:50–2:35 — Desk reconciliation, fulfilment and inventory proof.
- 2:35–3:00 — support + Notion write/readback + honestly stated limits.

## Submission readiness checklist
### Directly verified from TSG emails
- [ ] A Google Drive **submission materials** link is sent in a reply to the existing TSG Labs email thread. Latest 9 Nov employer response specifically requested that link.
- [ ] State preferred role: **Product**. Late submission accepted 3 Nov, "send as soon as you can"; no replacement exact date confirmed.
- [ ] Working Chord teammate(s), simulator/testing evidence included per assignment invitation.

### Internal Tally submission pack (strongly recommended; original public brief not accessible for cross-check)
- [ ] Authenticated simulator transcript/screenshots with **real** Desk/Shop tool steps and outcome.
- [ ] Video ≤3 minutes with genuine action, playback-tested and accessible to reviewer.
- [ ] Public GitHub source link with pinned tested/deployed commit, skills, tests, README.
- [ ] Brief product rationale + technical tradeoffs/security/sandbox limits.
- [ ] Deployment field notes and merchant handoff (already drafted, need refresh against 12 Nov release).
- [ ] Working sanitized evidence bundle (order/payment/support/provider/Notion proof).
- [ ] Drive folder sharing verified in incognito/external access, no credentials or private test tokens.
- [ ] Submission email actually sent, timestamp/message ID recorded in the tracker.

**If provider onboarding is blocked, do not let feature expansion prevent sending the submission:** do the already working core sandbox payment-reconciliation demonstration, label synthetic vs provider, note blocking gates transparently and submit the required Drive package. Avoid more status-chasing emails.

**Important:** no TSG email should be sent without founder instruction.
