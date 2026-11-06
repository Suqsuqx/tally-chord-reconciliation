# Human support handoff and recovery: two paths, one customer

## Path A — customer case escalated to Tally Desk

1. Shop creates a Tally support case for uncertain/complaint customer input.
2. Desk lists open cases; authenticated Operator or Admin writes a case-specific reply.
3. Backend stores answer with staff actor. The customer can retrieve it via Shop; an outbound notification is allowed only after verifying the actual messaging delivery bridge.
4. The merchant catch-up flags cases waiting over ten minutes. This is a **reporting threshold**, not yet an automatic push alert.

This path is implemented in the sandbox backend and tested locally.

## Path B — Chord native takeover of the customer conversation

Chord documentation describes `handover_to_human` on channel-bound turns, a thread state `agent_active → human_active`, human `POST /v1/threads/{id}/messages`, then `POST /v1/threads/{id}/hand-back` to return control to Shop. `conversation.escalated` webhook can notify a system when the takeover happened. The native operator acts on **the customer's thread**, not through a separate message to Tally Desk.

This requires a channel with a working return path. The documented external-chat bridge signs inbound messages and returns human and agent replies via a callback; the TSG simulator's exact support must be verified end-to-end. Recording a support case in Desk is not equivalent to handing over the Chord customer thread.

## Idle takeover recovery

Desired SLA: if the human has not responded to an escalated conversation after ten minutes, flag it as overdue, alert Admin/other Operator and keep the context visible. Do **not** automatically seize a human-owned thread or make promises. Native Chord manual `hand-back` and `take-over` exist; an automated watchdog, proactive notifications and queue reassignment would require event/webhook integration and idempotent timers that are not yet built.

## Simulator verification checklist

- Shop complaint creates case and, where supported, triggers `handover_to_human`.
- Confirm native thread `control_state=human_active` and `conversation.escalated` event.
- Human sends a real response to the same simulator customer; check `delivery_status` is `sent`, not merely HTTP success.
- Confirm Shop remains silent during takeover.
- Human hands back; Shop handles the next turn again.
- Simulate unanswered complaint; confirm visible merchant overdue report and document the unimplemented/verified delivery path.

Docs: https://api.chordhq.xyz/docs/threads/ ; https://api.chordhq.xyz/docs/escalation-rules/ ; https://api.chordhq.xyz/docs/external-chat/
