# VPS deployment checklist — additive, sandbox-only

This package has not been deployed. It is written for an existing Linux VPS and intentionally does not overwrite existing services. You need SSH access, an available DNS subdomain, ports 80/443 reachable and a reverse proxy with TLS. The backend currently uses one process on SQLite persistent disk; do not run multiple Uvicorn workers until the design is retested.

1. **Upload project:** Copy `Tally_Reconciliation_MVP_v1.2_Source.zip` to the VPS and unzip to `/opt/tally/current` under a dedicated unprivileged `tally` service account. Preserve ownership and deny unnecessary read access to `.env`.
2. **Set up dependencies:** Within `/opt/tally/current`, `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. Run `.venv/bin/python -m pytest tests -q` and stop on failures.
3. **Secrets:** Copy `.env.example` to `.env`. Set `TALLY_ENV=sandbox`, an absolute persistent database path such as `/opt/tally/data/tally.db`, and three different `openssl rand -hex 32` values for Shop/Desk MCP and signed-provider webhook. Restrict file permissions (`chmod 600 .env`) and let the service account access database directory.
4. **Service:** Adapt `tally.service.example`, place at `/etc/systemd/system/tally.service`, then `systemctl daemon-reload && systemctl enable --now tally`. Check `journalctl -u tally -n 80 --no-pager` and `curl -sS http://127.0.0.1:8787/healthz` for `status: ok`.
5. **HTTPS:** Use an available subdomain. If Caddy is present, merge `Caddyfile.example` into the existing configuration and reload safely; if Nginx is present, add a separate HTTPS virtual host. Do not disturb other VPS apps. Test `https://YOUR_HOSTNAME/healthz` and ensure TLS and an HTTPS POST work. Do not publish secrets.
6. **MCP discovery:** With the Shop bearer only, `POST /mcp/shop` with JSON-RPC `tools/list` and verify `upsert_product` is absent. With the Desk bearer, verify `get_reconciliation_report` is present. Repeat with wrong credentials and expect 401.
7. **Chord registration:** Follow `docs/CHORD_SETUP.md`. Assign each teammate to its specific MCP server (nonempty allowlist), run Chord's remote tool discovery and health, and perform a real simulator action.
8. **Field notes:** Record actual command output, request IDs, errors, fixes and confirmed simulator behavior. Do not claim a Chord connection succeeded based solely on localhost tests.

**Security gate:** This release explicitly refuses production mode; sandbox codes are not WhatsApp identity attestation. A production release needs provider-signed sender binding, hardened tenancy, durable payment adapter, notification delivery monitoring and operational readiness beyond the exercise.
