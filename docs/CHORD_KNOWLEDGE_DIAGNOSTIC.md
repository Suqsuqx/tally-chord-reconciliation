# Chord Knowledge library loop — diagnosis, not guesswork

The Chord Knowledge documentation separates four distinct states: **bundle created**, **document indexed**, **bundle shared/attached to teammate**, and **retrieval used in reply**. The “New library for this teammate” UI repeating is not evidence that creation persisted or failed; check the API state.

## Preferred UI check

1. In Chord, inspect **Tally Shop → Settings → Knowledge → Sources**, leave the create dialog and look for selected/attached sources. Do not keep creating similarly named libraries.
2. Open **Knowledge** at workspace level (if available), inspect whether the newly named library exists and whether its documents are indexed.
3. Test a unique sentence from a knowledge file in the teammate chat, then use **Why this reply** / execution details (if shown). Successful upload alone does not establish that retrieval ran.

## Definitive API checks

In a shell on your computer (or in the VPS, not in ChatGPT), set these locally with your own Chord API key and actual IDs:

```bash
export CHORD_BASE_URL='https://api.chordhq.xyz'
export CHORD_API_KEY='YOUR_CHORD_SCOPED_API_KEY'
export CHORD_WORKSPACE_ID='YOUR_WORKSPACE_ID'
export CHORD_SHOP_ID='YOUR_SHOP_TEAMMATE_ID'
export CHORD_DESK_ID='YOUR_DESK_TEAMMATE_ID'

# 1. Did Chord create the libraries?
curl -sS "$CHORD_BASE_URL/v1/knowledge/bundles?workspace_id=$CHORD_WORKSPACE_ID" \
  -H "Authorization: Bearer $CHORD_API_KEY"

# 2. Can Shop see any attached/accessible library?
curl -sS "$CHORD_BASE_URL/v1/knowledge/bundles/accessible?teammate_id=$CHORD_SHOP_ID&workspace_id=$CHORD_WORKSPACE_ID" \
  -H "Authorization: Bearer $CHORD_API_KEY"

# 3. Which bundle IDs are attached in teammate configuration?
curl -sS "$CHORD_BASE_URL/v1/teammates/$CHORD_SHOP_ID" \
  -H "Authorization: Bearer $CHORD_API_KEY"

# 4. Substitute a real returned bundle id:
export CHORD_BUNDLE_ID='kb-...'
curl -sS "$CHORD_BASE_URL/v1/knowledge/bundles/$CHORD_BUNDLE_ID/documents" \
  -H "Authorization: Bearer $CHORD_API_KEY"
```

**Interpret results:**

| Observation | Most likely next action |
|---|---|
| Bundle absent in #1 | Creation not persisted or wrong workspace; check UI request errors, permissions `rag:ingest`, and workspace selection. |
| Bundle exists; document list empty | Upload never completed. Upload once and inspect response/ingest status. |
| Document `PROCESSING` / `FAILED` | Read ingest error and retry only the failed upload. |
| Bundle/doc exist, but Shop absent from access list or teammate `bundles` | Attach/share the library to Shop once; do not create a new library. |
| Bundle attached, indexed, but reply ignores it | Test `/v1/knowledge/search` and inspect actual reply retrieval steps / Why this reply. |
| API sees records, UI doesn't | Likely UI state/cache/permissions issue; record screenshot, URL, response IDs and browser network error for TSG field notes. |
| `403` / `401` | Insufficient scoped key permissions or authentication issue; don't mistake access failure for non-persistence. |

The API supports sharing an existing bundle to a teammate:

```bash
curl -sS -X POST "$CHORD_BASE_URL/v1/knowledge/bundles/$CHORD_BUNDLE_ID/shares" \
  -H "Authorization: Bearer $CHORD_API_KEY" -H 'Content-Type: application/json' \
  -d "{\"teammate_id\":\"$CHORD_SHOP_ID\"}"
```

It also supports `PUT /v1/teammates/{id}` with `add_bundles`, but requires `teammate:update`. Avoid attaching merchant-only documentation to Shop.

If the app/API truly misbehaves, record the exact steps, timestamp, request ID, returned error and resulting bundle list in the **actual** TSG field notes; never claim you fixed a UI bug without verifying it.

Documentation: https://api.chordhq.xyz/docs/knowledge/ and https://api.chordhq.xyz/docs/build-a-teammate/
