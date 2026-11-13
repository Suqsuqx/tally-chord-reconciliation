# Tally deployment field notes — observed 6 November 2026

These notes distinguish live observations from pending assessment evidence. All identities, orders and payments below are synthetic sandbox records. Credentials, link codes, session tokens, signatures and raw confidential responses are intentionally omitted.

## Environment verified

- Linux service `tally.service`, one Uvicorn worker, loopback port `8787`.
- Existing Nginx/TLS reverse proxy; public health at `https://tally.mbrelabs.world/healthz` returned `status: ok` and `environment: sandbox`.
- Nginx syntax passed. Unrelated duplicate-server-name warnings for another project were observed and left untouched.
- Persistent SQLite ledger outside the release directory. Its mode was tightened from `0644` to `0600`.
- A consistent SQLite backup was made before the live journey.
- The deployed directory was not a Git checkout, so no source revision or remote could be proven from it.

## What failed, how it was handled, and what changed

| Step | Observed result | Diagnosis | Change or workaround | Verification |
| --- | --- | --- | --- | --- |
| Initial teammate scope audit | Shop pointed to the 11-tool Desk server; Desk pointed to the 7-tool Shop server | Redacted Chord teammate and MCP list/readback | Corrected only the two singleton assignments while both operational servers remained disabled | Fresh API readback: Shop→Shop, Desk→Desk, Assistant→disabled sentinel; no empty scopes |
| MCP activation | Both servers initially disabled as intended | Scope audit passed after correction | Enabled only Shop and Desk; sentinel remained disabled | Chord health `ok`; exactly 7 Shop and 11 Desk tools |
| First Desk follow-up turn | Desk linked successfully, but a later turn did not reuse the private tool session and attempted `link_identity` again | Tool step trace showed successful link followed by failed re-link on the next turn | Link and perform the required private read within one tool loop | Chord step trace showed successful `link_identity` then `get_catalog` |
| Restricted test run | Pytest stalled after two cases inside the network/thread-restricted execution sandbox | FastAPI `TestClient` worker behavior was constrained by the sandbox, not by Tally | Re-ran unchanged tests on the host with bytecode/cache disabled and temp output isolated | `9 passed` in 2.05s before and `9 passed` in 2.33s after live verification |
| Channel simulator | Public page showed “Sign in with Chord” | No authenticated browser context was available to the verifier | Preserved credits and stopped additional teammate turns | Simulator UI, video and native handoff remain explicitly unverified |

## Actual Chord-origin journey

Synthetic order `TLY-5d134215d2fb` ordered three brownie boxes for `1,950,000` kobo.

1. Tally Shop invoked `link_identity`, `get_catalog`, `create_order`, `record_payment_claim` and `get_my_order`.
2. The customer claim left the order `awaiting_payment`.
3. A bad signature returned HTTP 401.
4. A signed one-kobo-short event became `amount_mismatch`; the order remained unpaid.
5. A signed unknown reference became `unmatched_reference`.
6. A valid exact signed event became `matched`; the order moved to `confirmed`.
7. Replaying the exact event was deduplicated. Reusing its event ID with changed data returned HTTP 400 `EVENT_ID_CONFLICT`.
8. Tally Desk invoked `get_reconciliation_report`, `get_merchant_catchup` and `get_inventory_alerts`.
9. An Operator advanced `confirmed → preparing → dispatched → fulfilled` through three tool calls.
10. Brownie stock ended at on-hand 2, reserved 0, low-stock threshold 2.

## Security and failure checks

The live HTTPS sandbox also passed:

- wrong MCP bearer → HTTP 401;
- missing and stale provider signatures → HTTP 401;
- second customer reading the first customer’s order → `NOT_FOUND`;
- Operator price/catalogue mutation → `FORBIDDEN`, persisted price unchanged;
- unpaid dispatch → `INVALID_TRANSITION`, status unchanged;
- Shop calling a Desk-only tool → `FORBIDDEN`;
- reused idempotency key with a changed basket → `IDEMPOTENCY_CONFLICT`;
- sold-out item → `OUT_OF_STOCK`, with no order persisted.

## Credit discipline

Approximately ten synthetic Chord external-chat requests were sent across connectivity probes and the complete journey. Actual platform credit accounting was not queried. Further agent turns are reserved for one authenticated simulator recording pass and, if necessary, one retry.

## Remaining evidence gaps

- TSG Channel simulator UI transcript and ≤3-minute recording.
- Native human takeover, operator delivery result and hand-back in the same customer thread.
- Chord Knowledge persistence/retrieval; this is lower priority than submission proof.
- Approved GitHub repository and pinned commit.
- Externally accessible Google Drive package and sent TSG email receipt naming Product as the preferred role.

## Rollback

If a scope or health regression appears, disable the affected operational MCP server through Chord. Keep the native Assistant’s disabled sentinel assigned and disabled. Restore the private pre-journey SQLite backup only after stopping the service and preserving the current database; no restore was required during verification.

## Provider connection release — 11–12 November 2026

Commit `141907d` introduced the default-off business-scoped Paystack setup/storage core and Tally-owned Notion OAuth/read-preview core. Before deployment, the source passed 33 tests and a private rollback set was created at 15:23 UTC on 11 November: current environment, source archive and a consistent SQLite backup whose integrity check returned `ok`.

The non-Git live checkout was updated without copying `.env`, `.venv`, caches or persistent data. The deployed copy passed the same 33 tests before service restart. `tally.service` restarted at 16:24 WAT with one worker. Reverification on 12 November observed:

- local and public `/healthz`: `status: ok`, `environment: sandbox`;
- additive provider tables present; SQLite integrity `ok`;
- zero provider connection and OAuth-state records;
- exact local authenticated discovery: 7 Shop tools and 11 Desk tools;
- Paystack and Notion connection POSTs fail closed while provider configuration is absent;
- deployed files match the committed branch source, excluding private/runtime paths.

No provider feature was enabled, no merchant credential was installed, no Notion OAuth grant occurred, no Paystack API request or payment was made, and no Chord/simulator credit was used for this deployment verification. Live acceptance remains blocked on Tally Notion app registration/private platform configuration and the owner's secure off-chat provider actions.

On 12 November, the platform-only machine configuration was advanced without enabling providers: a new 32-byte credential-encryption key and version, explicit false Paystack/Notion flags, exact HTTPS Notion callback and API version were installed in the private mode-`0600` environment. The key length and redacted preflight passed, a post-configuration private environment backup was saved, the service restarted active, public health stayed OK and Notion setup still failed closed. Tally's Notion OAuth client ID/secret are still absent; merchant Paystack keys and webhook secrets remain absent by design.

## Conversational onboarding release — 12 November 2026

Commit `cd649bf` adds sandbox sender-routed merchant registration, tenant-scoped Shop activation, merchant-approved file/Notion import previews, optional-webhook Paystack restricted-key setup, hosted TEST checkout initialization, claim-triggered Paystack verification and separately labelled manual-bank confirmation. The simulator sender field is explicitly unverified and is not presented as WhatsApp authentication; the live contract remains provider-authenticated phone identity.

Before deployment, a private environment/source snapshot and consistent SQLite backup were created; source and backup integrity checks returned `ok`. Source and deployed copies passed `37 tests`. The additive migration added business routing/settings, Notion resource summaries and checkout metadata. Aggregate row counts for all pre-existing core tables were unchanged, routing rows remained zero and provider connections remained zero. After restart, the one-worker service was active, local/public `/healthz` returned sandbox `status: ok`, SQLite integrity was `ok`, and authenticated local MCP discovery remained exactly 7 Shop / 11 Desk tools with the same names.

Tally's private Notion OAuth client configuration and both provider feature flags are enabled, but no merchant provider credential or OAuth grant has been submitted. No real Paystack initialization/verification, Notion read/import, Chord-origin onboarding call or simulator journey is claimed by this deployment record. Those remain acceptance actions initiated by the merchant through Tally Desk.

The existing Chord teammates were updated in place—no duplicates were created and no chat/model turn was used. `Customer Skill` and `Merchant skill` were saved, reviewed and published as revision 4 (skill version 8), included for future replies, with no pending drafts. A fresh redacted Chord audit passed every teammate/sentinel/scope check; remote health was `ok`, Shop discovery was exactly 7 tools and Desk discovery exactly 11.

## Empty merchant registration and Notion workspace sync — 12 November 2026

Commit `82d844e` replaces the earlier Cedar-row rename shortcut. A message such as “I want to register ASYAN SHOP” now creates a new empty business and Admin membership at that moment. It does not copy a catalogue or claim a pre-registered merchant. Profile, catalogue and policy data arrive afterward through conversation, uploaded files or an approved Notion preview; Shop activation still requires at least one approved product and a payment method.

Notion remains approval-gated and SQL remains authoritative. After OAuth and explicit selection/approval of an authorized parent page, Tally can create five merchant-readable sections—Business Profile, Catalogue, Policies & FAQ, Orders, and Activity & Reconciliation—and mirror approved profile, policy, product and order snapshots into them. The Notion connection must have read content, insert content and update content capabilities. Local mocked tests prove the integration logic and authorization boundary; they are not evidence of a genuine ASYAN SHOP OAuth grant or write/readback.

Before deployment, a private source/environment/SQLite backup was created at `/home/mojiwoji/Tally/backups/20261112T201013Z-empty-registration-notion-sync`; backup integrity returned `ok`. The deployed copy passed `39 tests`. The additive schema created `notion_workspaces` and `notion_records`. The one stale simulator-generated owner was deactivated (not deleted), its setup sessions were consumed, and the legacy fixture was restored to Cedar Bakes with its historical products and orders intact. Post-reset checks found zero ASYAN business names, zero `asyan-shop` slugs and SQLite integrity `ok`.

After restart, the one-worker service was active and local/public `/healthz` returned sandbox `status: ok`. Authenticated local and public discovery remained exactly 7 Shop / 11 Desk tools. The existing Tally Desk skill was published in place at revision 5 (container version 10), remained included, had no draft and byte-matched the deployed `SKILL.md`. The redacted Chord audit passed every teammate/scope/server check and both MCP health probes. No new teammate and no Chord chat/model turn were created.

No merchant Paystack credential or Notion OAuth token was submitted during this deployment. The next simulator message is therefore the genuine ASYAN SHOP creation event; live provider setup and Notion write/readback remain acceptance steps for the merchant.

## Tenant-bound Shop and onboarding UX repair — 12 November 2026

An authenticated simulator transcript exposed a real tenant-boundary defect: Tally Shop called `get_catalog` without a session or shop slug, and the backend silently selected the Cedar Bakes regression tenant. The response therefore showed Cedar's current stock even though the simulator channel was labelled ASYAN SHOP. This was backend behavior, not evidence that ASYAN SHOP's import had failed.

The runtime no longer seeds a merchant at process startup and `get_catalog` has no default tenant. An unbound catalogue request now returns `SHOP_CONTEXT_REQUIRED`; a session or active storefront slug is mandatory. Customer sessions also recheck the business's active status on every Shop operation. The historical Cedar tenant was backed up and changed from active to archived without deleting its records; ASYAN SHOP remained the only active shop. A redacted live smoke test returned the expected unbound error and returned ASYAN SHOP with three products only when scoped to `asyan-shop`.

The Desk onboarding boundary now accepts tool transports that serialize approved profile, policy or manual-bank containers as JSON strings, while still rejecting prose and rolling back the whole write on malformed input. Shop activation continues to require only one approved product plus Paystack or manual bank; profile details, FAQs, policies, Notion workspace mirroring and webhook signing are optional. Desk instructions now lead with outcomes, separate status from next actions, use compact lists only when helpful and ask one clear question at a time.

The complete source suite passed **46 tests**. Local and public health remained OK. A fresh redacted Chord audit passed all scope/sentinel checks and discovered exactly 7 Shop and 11 Desk tools. Existing skills were updated in place—no teammate or chat turn was created. `Customer Skill` and `Merchant skill` published version 7 were included, had no drafts and byte-matched the deployed `SKILL.md` files. The Shop skill binds the assessment channel labelled Asyan Shop to `asyan-shop`, forbids generic/default merchant behavior and requires the tenant name returned by a tool rather than Mbre, Cedar or workspace branding. A fresh simulator conversation remains the required behavioral acceptance test.

## Generic Desk and single-business Shop binding — 13 November 2026

The runtime no longer contains a seeded or named demo merchant. Legacy regression data moved into a generic test-only module that production code never imports, and the server-only code issuer now operates only on an explicitly supplied existing actor. A fresh source scan found no merchant name or slug in `server/`, `skills/`, `scripts/` or `.env.example`.

Desk instructions now derive the exact business name from the merchant's current request and never substitute an example or previously tested business. An isolated registration test created **Kora Books and Gifts**, derived `kora-books-and-gifts`, began empty/private in `onboarding`, and was denied activation through ASYAN's separately provisioned Shop channel. This proves registration is generic while customer-channel ownership stays isolated.

The Shop MCP schema exposes no `business_slug` or `shop_slug` selector. `TALLY_SHOP_BOUND_SLUG` is injected by the backend for `link_identity` and public catalogue reads, and every customer session is checked against that binding. A forced alternate slug returned `SHOP_CONTEXT_MISMATCH`. Activation now requires the existing merchant gates—at least one approved product and a payment method—plus a deployment-owned matching Shop binding and HTTPS agent target; profile, policies, FAQs, Notion and optional webhook signing remain non-blocking.

Successful activation/resumption returns `shop_access` with the active slug and stable `https://tally.mbrelabs.world/shop/{slug}` entry. The ASYAN entry returned HTTP 307 to the configured TSG simulator, while an unrelated slug returned HTTP 404. This assessment deployment privately binds the existing Shop MCP instance to `asyan-shop`; the values are not present in Git, skills or merchant-authored data.

Before deployment, a private source/environment/SQLite rollback set was created at `/home/mojiwoji/Tally/backups/20261113T100934Z-shop-agent-binding`; SQLite integrity was `ok`. Source and live checkout passed **50 tests**. After restart, local/public health remained OK, the bound catalogue returned ASYAN SHOP with three products, the malicious switch failed, and discovery remained exactly 7 Shop / 11 Desk tools. Existing `Customer Skill` and `Merchant skill` were published in place as version 8, included with byte-matched files and no drafts. No new teammate or simulator/model turn was created; a fresh human simulator conversation remains the behavioral acceptance step.

## Customer memory, guided onboarding and delivery confirmation — 13 November 2026

Desk onboarding is now presented as four readable sections—business profile, catalogue, policies and payment—with chat, document and Notion setup paths. It asks one question at a time, skips fields the merchant already supplied and previews grouped changes before saving. Catalogue plus a configured payment method remain the only Shop activation gates; profile details and policies remain useful but non-blocking.

Shop now remembers an authenticated customer's display name and optional payment email within the bound business. It automatically follows the merchant's configured payment method instead of offering an unsupported choice. For Paystack hosted Checkout, email is collected once and reused because Paystack requires an email before transaction initialization can return a checkout URL; no claim is made that Checkout can collect the email before initialization.

Paid-order completion now supports informal offline operations without forcing artificial one-step updates. A merchant may move a paid order forward to preparing or dispatched, or report it delivered even if intermediate updates were missed. A merchant delivery report records `delivery_reported` and queues a request for the customer to confirm receipt. The simulator has no verified outbound-customer messaging API, so Tally does not falsely claim that the prompt was delivered; Shop surfaces the pending confirmation when that customer next contacts it. Customer confirmation promotes the order to `fulfilled` and deducts stock exactly once. A customer mismatch leaves the order at `delivery_reported` and opens a support case. Desk may record fulfilment from an explicit offline customer confirmation, with the confirmation note retained in the audit trail.

The additive database migration introduced the optional customer email field and a tenant-scoped customer-notification queue. Existing merchant, customer and order data were preserved. Before migration, a private source/environment/SQLite rollback set was created at `/home/mojiwoji/Tally/backups/20261113T123839Z-customer-memory-delivery-confirmation`; backup SQLite integrity returned `ok`.

Source and deployed checkouts passed **54 tests**. After restart, the one-worker service was active, local and public health returned OK, live SQLite integrity remained `ok`, the new column and queue were present, ASYAN SHOP's existing order was preserved, and authenticated discovery remained exactly 7 Shop / 11 Desk tools. The stable ASYAN Shop entry returned HTTP 307 to the configured TSG simulator on GET.

The existing `Customer Skill` and `Merchant skill` were published in place as revision 9 (container version 18), included, byte-matched and left with no drafts. A fresh redacted Chord audit passed every teammate, scope, disabled-sentinel and backend probe. No new teammate and no simulator/model turn were created. ASYAN assessment data was not reset; the final recording reset remains a separate deliberate action.

## OAuth-authorized automatic Notion workspace — 13 November 2026

An authenticated Desk trace showed that Notion had connected successfully, but Tally then rejected four workspace attempts with its own `APPROVAL_REQUIRED` guard because the assistant omitted `approved=true`. Notion had not rejected the writes; the subsequent merchant reply incorrectly blamed page sharing and edit permission. The redundant chat-level approval gate was removed.

The secure linking page now states that continuing authorizes Tally to read the one selected business workspace page and create or update its managed Business Profile, Catalogue, Policies & FAQ, Orders, and Activity & Reconciliation sections. A successful OAuth callback selects the unique authorized workspace root, creates the five sections and backfills current approved profile, product, order and support records. No `notion_workspace` field remains in the Desk schema and no second “yes, approved” chat turn is required. Importing merchant-authored source content into SQL remains separately previewed and approval-gated.

Ongoing synchronization now covers profile/policies, catalogue edits, stock adjustments, order creation, payment claims and verified payment updates, fulfilment changes, customer disputes/support cases and staff support replies. SQL remains authoritative; a Notion mirror failure cannot reverse a valid transaction. Support cases are mirrored under Activity & Reconciliation.

The already-authorized ASYAN SHOP OAuth connection was repaired without requesting another grant. Tally created all five managed sections and backfilled three products and one order; no support cases existed. A real Notion API readback returned HTTP 200 for all nine managed and record pages. This is genuine OAuth write/read evidence, not a mocked test claim. Before the repair, a private environment/source/SQLite rollback set was saved at `/home/mojiwoji/Tally/backups/20261113-auto-notion-sync`; backup integrity returned `ok`.

Source and deployed checkouts passed **56 tests**. Local and public health remained OK. The existing `Customer Skill` and `Merchant skill` were published in place as revision 11 (container version 22), included, byte-matched and left with no drafts. A fresh redacted Chord audit passed all teammate/scope/sentinel checks and discovered exactly 7 Shop and 11 Desk tools.

A subsequent Desk reply exposed a separate status-contract defect: every Admin identity refresh issued another short-lived provider setup URL even when Notion and Paystack were already connected, while the standard response did not explicitly say the Notion workspace was active. Desk therefore resurfaced an expired URL and contradicted verified state. Staff identity and onboarding results now include redacted provider connection/workspace status. Connected providers return status only; an active Notion workspace never returns a setup URL. Fourteen accumulated unused Notion links were expired. A live contract check returned `connected`, `workspace_status: active`, five managed sections, zero unused links and no `setup_url`. The regression suite increased to **57 tests**, and both existing skills were published in place as revision 12 (container version 24).
