# Codex instructions — Tally reconciliation sandbox

Read `README.md`, `docs/MVP_SCOPE_v1.2.md`, `docs/TOOL_REGISTER.md` and `docs/DEPLOYMENT_FIELD_NOTES.md` before changing this project. Read the actual source (`server/`, `tests/`, `skills/`, `docs/`) and inspect the VPS before making assumptions. Treat the on-VPS checkout, Chord API results and simulator traces as different evidence layers.

## Objective

Maintain the existing Tally v1.2 Chord Build Exercise as a **working, independently verifiable sandbox**, not a prototype rebuilt from scratch. Backend, Chord API and synthetic journey verification are complete. Remaining priorities are authenticated Channel simulator capture, native handoff evidence, an approved GitHub destination, the short recording and final Drive/email submission.

## Verified operator status (6 November 2026)

- Active `TallyShop` renamed via Chord API to **`Tally Shop`**, with same ID; `.env` variable renamed to `TALLY_SHOP_ID`.
- Existing **`Tally Desk`** is active and separately assigned to its Desk MCP server.
- Old duplicate retired `Tally Shop` teammate was permanently deleted; DELETE returned **204**.
- A fresh audit found Shop and Desk assigned to each other’s server. The two singleton assignments were corrected while both servers were disabled.
- Native **`Chord Assistant`** is restricted to an explicit **disabled, credential-free MCP sentinel**, not the operational Shop/Desk servers.
- Operational Shop and Desk servers are enabled; Chord health is `ok`, discovery returns exactly seven and eleven tools, and actual Chord-origin calls succeeded for each.
- VPS service/TLS and the sandbox journey were verified. Tests passed before and after (`9 passed`). The Channel simulator UI and native handoff remain unverified.

## Rules (non-negotiable)

1. **SANDBOX only; never use real payments or customer data.** Do not change `TALLY_ENV` to production.
2. **Customer claims never confirm payment.** Only a valid, fresh, HMAC-signed sandbox provider event can do so.
3. Never copy `.env`, `CHORD_API_KEY`, MCP bearer tokens, webhook secret, sandbox link codes, session tokens, DB data, or raw confidential logs to chat, docs, GitHub or recordings.
4. Keep **Tally Shop** on **Shop-only MCP** (seven tools), **Tally Desk** on **Desk-only MCP** (eleven tools). Chord `mcp_server_ids: []` means **all enabled servers**, not none. Keep the native Assistant's sentinel disabled; do not remove its singleton assignment.
5. Enforce Admin/Operator/Customer authorization **in backend code**. One-time sandbox codes do not prove real WhatsApp sender ownership.
6. Avoid changes to other VPS projects; **Nginx already serves several apps**. Do not install Caddy, replace shared reverse-proxy config, alter unrelated services or erase `~/Tally/data/tally.db`.
7. Preserve data: consistent SQLite backup before destructive changes, no arbitrary resets/reseeds, one worker unless concurrency revalidated.
8. Run `.venv/bin/python -m pytest tests -q` before and after changes. Record exact pass/fail. Test through Chord before claiming integration.
9. For REST calls: finite timeouts, check HTTP status, inspect error bodies, never parse empty failed responses as JSON. Health HTTP 200 with `status:error` is **failure**.
10. Do not push to a new/unapproved GitHub repo or claim a deployment that has not actually happened. Inspect Git status and scan staged files for secrets.

## Key paths, identifiers, APIs

- Checkout: repository root.
- App: `server/app.py` and `server/business.py`; MCP schema: `server/mcp.py`; SQLite: `server/db.py`.
- VPS service: `tally.service`, one worker on `127.0.0.1:8787`; public host `https://tally.mbrelabs.world`.
- Private `.env` names include `CHORD_API_KEY`, `WORK_SPACE_ID`, `TALLY_SHOP_ID`, `TALLY_DESK_ID`, `TALLY_SHOP_MCP_TOKEN`, `TALLY_DESK_MCP_TOKEN`, `TALLY_WEBHOOK_SECRET`, `TALLY_DB_PATH`. Native assistant key may historically have the typo `CHORD_ASSITANT_ID`; discover it from Chord if necessary.
- Chord REST: `https://api.chordhq.xyz/v1`.
- Exact Chord names: `Tally Shop`, `Tally Desk`, `Chord Assistant`; MCP: `Tally Sandbox Shop`, `Tally Sandbox Desk`, `Chord Assistant MCP DENY (disabled)`.
- Chord scope changes: `PUT /v1/teammates/{id}` with nonempty `set_mcp_server_ids`. Server enable: `PUT /v1/workspaces/{ws}/mcp-servers/{id}` with `{"enabled":true}` **only after full audit**. `POST .../{id}/health` and `POST .../{id}/tools` with no request body.
- Signed payments: `POST /sandbox/provider-event`, never an MCP tool; `scripts_utility.py sign-event` is a local admin-only helper.

## Immediate first actions

1. Re-run service/HTTPS/tests and `scripts/chord_audit.py --probe` before any deployment claim.
2. Preserve the remaining Chord credits for the authenticated Channel simulator recording. Do not repeat already-proven API journeys without a concrete failure reason.
3. Capture Shop order/claim and Desk reconciliation/fulfilment in the simulator, then test native takeover/delivery/hand-back separately.
4. Prepare a clean commit and secret scan, but do not invent or push to an unapproved GitHub destination.
5. Finish the ≤3-minute recording, Drive package and email only after every included claim is visible and playback/access tested.

## Reporting

After each phase, report: **Verified / Changed / Tests / Blockers / Rollback / Next** with timestamps. The mere presence of a tool in Chord's workspace dashboard is not evidence of teammate authorization or actual tool execution. A staff-written support-case message is not evidence of channel delivery or native human takeover.
