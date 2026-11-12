# Merchant provider connections — activation and acceptance gates

This branch implements default-off connection flows for merchant-owned Paystack TEST accounts and merchant-selected Notion content. It does not contain merchant credentials and it does not prove that either provider is live.

## Deployment record

The code was deployed to the existing sandbox with both provider features default-off at 16:24 WAT on 11 November 2026 and reverified on 12 November. The source and deployed copy passed 33 tests; local and public health returned sandbox `status: ok`; SQLite integrity was `ok`; the four additive provider tables exist; provider connection and OAuth-state counts were zero; local authenticated MCP discovery remained exactly 7 Shop / 11 Desk tools; and provider setup POSTs failed closed while configuration was absent. A private source/environment snapshot and consistent SQLite backup were created before deployment. On 12 November, a generated 32-byte platform encryption key/version, explicit false feature flags, exact Notion callback and API version were installed in the private mode-0600 environment and backed up without printing values; restart/health/fail-closed checks passed. Tally's Notion client ID/secret remain unconfigured. This is deployment evidence only, not a Paystack or Notion acceptance pass.

## Security model

- Only an active business Admin may receive setup links. Operators and customers are denied.
- Setup bearer values and OAuth state are random, short-lived, stored only as SHA-256 hashes and consumed once.
- Setup bearer values stay in URL fragments, are removed from the browser address before requests and are never environment variables.
- Paystack restricted keys and webhook signing secrets are submitted directly to Tally's HTTPS form, validated, then AES-GCM encrypted against the business and connection identifiers.
- Notion client ID/secret are Tally platform credentials. Merchant access/refresh tokens are OAuth results encrypted per business; refresh rotates both tokens.
- Notion's authorization prompt is the page picker. Search and reads use only the resulting business token. Returned document content is bounded and labelled untrusted merchant data; it is never interpreted as instructions and is not imported without a later approval step.
- Provider features remain disabled unless explicitly enabled after preflight, backup, migration and rollback preparation.

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

1. Register Tally's OAuth integration in Notion with read-content capability and the exact HTTPS callback above.
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
5. Tally generates a bounded preview; no SQL business record is created until a separate Admin approval/import gate is implemented and tested.

PASS requires sanitized HTTP/tool traces, ciphertext-only database inspection, single-use/replay failures and actual provider responses. A locally mocked test, a setup page, a connection record or a user claim is not live-provider proof.

## Explicitly still out of scope for this gate

- Live-provider acceptance of Paystack transaction initialization, hosted test checkout and claim-triggered API verification. The implementation and mocked security tests are present, but genuine Paystack responses remain unverified.
- Approved catalogue/profile/policy import into SQL.
- Notion Orders write and readback.
- Trusted WhatsApp sender authentication, multi-business customer routing and the final simulator recording.
