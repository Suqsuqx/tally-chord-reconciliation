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
