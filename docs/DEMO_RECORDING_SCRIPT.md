# Tally three-minute demo — low-credit recording plan

Target: one clean authenticated Channel simulator pass, three teammate turns maximum, no retries unless a turn fails. Prepare codes and the signed-event command off-camera. Never display codes, tokens, signatures, `.env`, raw logs or private database contents.

## Preflight off-camera

- Run tests and `scripts/chord_audit.py --probe`.
- Confirm Shop/Desk scopes, both operational servers healthy and the Assistant sentinel disabled.
- Issue fresh customer, Admin and Operator sandbox codes immediately before recording.
- Choose an in-stock item/quantity that reaches the low-stock threshold.
- Prepare a terminal with only the safe signed-event command/output region visible; mask the signature before capture.
- Open separate Tally Shop and Tally Desk simulator conversations.

## Recording timeline

### 0:00–0:20 — problem and architecture

“Tally keeps a small merchant’s order, verified payment, fulfilment and stock records consistent from a WhatsApp-style conversation. Shop is customer-only; Desk is staff-only; payment verification is independent of the model.”

Show the two published teammates and the sandbox banner. Do not dwell on settings.

### 0:20–1:05 — customer order and unverified claim

Use one prepared Shop message that privately links the sandbox customer, requests the catalogue, explicitly approves one basket, creates the order once, records the payment claim and reads the resulting status.

Show:

- actual item, total and order reference from tools;
- `record_payment_claim` tool trace;
- order still `awaiting_payment`.

Narration: “The customer’s transfer statement is recorded but cannot mark the order paid.”

### 1:05–1:30 — independent signed event

Submit the prepared signed sandbox event from the VPS. Show only safe response fields: order reference, `match_status: matched`, and the order becoming `confirmed`. Briefly mention that wrong amount, missing/stale signature and duplicates were separately tested and are documented in the field notes.

### 1:30–2:30 — merchant reconciliation and action

Use one prepared Desk message that privately links a staff actor, requests reconciliation/catch-up and stock alerts, advances the confirmed order through valid fulfilment states, then rechecks inventory.

Show:

- verified matched receipt separated from claims/exceptions;
- catch-up grounded in tool calls;
- `confirmed → preparing → dispatched → fulfilled`;
- actual low-stock warning.

### 2:30–3:00 — trade-offs and limits

“This is an assessment sandbox. Identity codes are not real WhatsApp ownership, the payment event is synthetic, and stored case replies are not delivery receipts. Production needs provider-signed identity, real payment webhooks, monitoring, retention controls and verified human handoff.”

End on the repository/field-notes link index, not on credentials or terminal history.

## Playback gate

- Duration is at or below three minutes.
- Tool traces are readable and correspond to the correct teammate.
- Claim visibly remains unpaid before the signed event.
- No credential, code, token, signature or personal data appears in any frame.
- Audio is understandable and the final file plays from the evaluator-facing Drive permission context.
