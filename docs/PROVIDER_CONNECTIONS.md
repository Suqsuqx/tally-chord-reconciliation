# Merchant provider connections — activation and acceptance gates

This branch implements merchant-owned Paystack TEST and Notion OAuth connection flows. The public repository contains no merchant credentials, and enabled setup routes do not prove that either provider has been connected or accepted live.

## Deployment record

The default-off provider core was deployed on 11 November. On 12 November, the merchant-onboarding release `cd649bf` was deployed after a private source/environment snapshot and consistent SQLite backup. Source and deployed copies passed 37 tests; the additive migration preserved every core-table row count; SQLite integrity remained `ok`; local/public health returned sandbox `status: ok`; and authenticated discovery remained exactly 7 Shop / 11 Desk tools. Tally's private Notion client configuration and both provider feature flags are now present/enabled. Provider connection count remains zero: no merchant Paystack key, webhook secret or Notion OAuth token has been submitted, and no genuine provider acceptance call is claimed.

## Security model

- Only an active business Admin may receive setup links. Operators and customers are denied.
- Setup bearer values and OAuth state are random, short-lived, stored only as SHA-256 hashes and consumed once.
- Setup bearer values stay in URL fragments, are removed from the browser address before requests and are never environment variables.
- Paystack restricted keys and webhook signing secrets are submitted directly to Tally's HTTPS form, validated, then AES-GCM encrypted against the business and connection identifiers.
- Notion client ID/secret are Tally platform credentials. Merchant access/refresh tokens are OAuth results encrypted per business; refresh rotates both tokens.
- Notion's authorization prompt is the page picker. The Tally setup page explains that continuing authorizes read access plus creation and maintenance of Tally's managed sections inside the one selected business workspace page. The successful OAuth callback creates those sections and backfills current approved products, orders and support cases; no second chat approval is required. Returned merchant-authored content remains bounded, labelled untrusted data and is never imported into SQL without separate approval.
- Provider features remain disabled unless explicitly enabled after preflight, backup, migration and rollback preparation.

## Customer checkout data

Paystack requires `email` and `amount` before its transaction-initialize endpoint returns a hosted checkout URL. The hosted page therefore cannot collect the email first. Tally asks for an email only when the merchant uses Paystack and no email is remembered for that authenticated customer; it then reuses the saved value on later orders. The merchant's configured payment method is selected automatically—Shop never asks customers to choose Paystack versus manual bank.

Paystack's enabled Checkout channels may include “Pay with transfer,” which generates a temporary bank account inside the hosted payment experience. A Dedicated Virtual Account is not the default substitute: it is a longer-lived customer facility, still requires email, name and phone, may require identity validation, and requires express customer consent.

## Platform configuration

Keep only Tally-owned platform configuration in the private service environment:

```text
TALLY_CREDENTIAL_ENCRYPTION_KEY=<base64url 32-byte key>
TALLY_CREDENTIAL_ENCRYPTION_KEY_VERSION=v1
TALLY_PAYSTACK_CONNECTIONS_ENABLED=false
TALLY_NOTION_CONNECTIONS_ENABLED=false
NOTION_CLIENT_ID=<Tally OAuth client ID>
NOTION_CLIENT_SECRET=<Tally OAuth client secret>
NOTION_OAUTH_REDIRECT_URI=https://tally.mbrelabs.world/integrations/notion/callback
NOTION_API_VERSION=2026-03-11
```

Do not place `rk_test_`, `whsec_`, Notion merchant tokens, setup tokens or OAuth state in `.env`, GitHub, Chord, Notion, chat, screenshots or recordings.

## Deployment gate

1. Register Tally's OAuth integration in Notion with read content, insert content and update content capabilities and the exact HTTPS callback above.
2. Back up SQLite consistently and retain the previous release and private environment for rollback.
3. Run the full suite and `scripts/check_integration_config.py` with both features disabled, then with the intended private configuration enabled.
4. Deploy the additive schema/code with both feature flags still false; verify health and the existing 7/11 Chord discovery.
5. Enable one provider at a time, restart, re-run preflight/health and perform only its stated acceptance test.
6. Disable the affected feature flag and restore the prior release if health, migration, encryption or Chord discovery regresses. The additive tables do not require a destructive rollback.

## First live acceptance test

The first acceptance stops before catalogue import or payment settlement:

1. ASYAN SHOP Admin links the existing sandbox identity and receives private provider setup links.
2. The Admin submits a Paystack TEST restricted key with `transactions:write` through the HTTPS form; Tally proves read plus initialize scope and stores ciphertext only. An independent `whsec_` signing secret is optional for instant webhook updates, not required for claim-triggered API verification.
3. The Admin opens Connect Notion, authorizes Tally's own integration and selects the intended ASYAN SHOP pages.
4. The callback exchanges and encrypts both OAuth tokens, discovers selected resources and probes actual page/data-source reads.
5. Tally generates a bounded preview. Approved fields are written to SQL, and—only after the Admin approves a parent page—mirrored into the structured Notion workspace.

PASS requires sanitized HTTP/tool traces, ciphertext-only database inspection, single-use/replay failures and actual provider responses. A locally mocked test, a setup page, a connection record or a user claim is not live-provider proof.

## Explicitly still requiring live acceptance

- Live-provider acceptance of Paystack transaction initialization, hosted test checkout and claim-triggered API verification. The implementation and mocked security tests are present, but genuine Paystack responses remain unverified.
- Genuine Notion workspace creation, approved write and readback in ASYAN SHOP's OAuth workspace. Mocked tests cover the local implementation only.
- Trusted WhatsApp sender authentication, multi-business customer routing and the final simulator recording.
