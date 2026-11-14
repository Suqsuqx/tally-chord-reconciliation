# Tally Merchant Handoff — ASYAN SHOP Assessment (Sandbox)
 
**Updated: 14 November 2026.** This note is for the ASYAN SHOP merchant and evaluators. Tally is an assessment sandbox, not a production WhatsApp commerce or payments deployment.

## What the merchant receives

**Tally Desk** helps an authorized owner or operator manage a business: catalogue, pending and verified orders, inventory, reconciliation, fulfilment and customer support. **Tally Shop** answers customer questions and handles orders within one activated business's Shop channel. For this assessment that business is ASYAN SHOP; Desk can register other businesses, but this Shop instance cannot switch merchant context.

Tally has three separate sources of responsibility:
- **Merchant records / Notion:** business-authored source material, policies and readable mirrored operations.
- **Paystack:** independently verified TEST transactions; a customer saying “I paid” is never enough.
- **Tally SQLite ledger:** operational source of truth for orders, reservations, inventory, payment status, cases and audit history.

## ASYAN SHOP setup

1. **Register in Desk:** tell Tally the real business name. A new business starts **empty**, with no pre-imported catalogue or unauthorized Notion connection.
2. **Provide business details:** complete business profile, catalogue, policies and payment in conversation, or supply merchant-owned CSV files. Data is previewed before approval. Profile/policies help Shop answer accurately; at least one approved product plus a configured payment method are the activation gates.
3. **Connect Notion (optional):** open Tally's private setup link, authorize its own Notion OAuth integration and select the existing business page. Tally creates or resumes five Tally-owned sections under that page—Business Profile, Catalogue, Policies & FAQ, Orders and Activity & Reconciliation—and mirrors approved SQL state. **Existing merchant-authored pages are not automatically imported into SQL**: their content must be previewed and approved separately. A real authorized Notion write/readback was documented on 13 November, before the final clean recording reset.
4. **Connect Paystack TEST (if chosen):** enter an account-owned `rk_test_` with **transactions:write** through the private HTTPS form, never in WhatsApp, Chord, a Git commit or Tally's platform `.env`. Tally stores it encrypted for the business; webhook signing is optional when claim-triggered API verification is used. A merchant may instead choose **manual bank**, with clearly labelled, audited Admin-only offline confirmation. This is not an automatic Paystack DVA: hosted Checkout may present “Pay with transfer” if enabled on the merchant's account.
5. **Activate Shop:** once an approved product and payment mode exist, Desk returns the business's stable Shop entry URL. The assessment Shop is bound server-side to ASYAN SHOP and cannot browse another tenant.

## Everyday customer and merchant experience

- Shop checks live stock and calculates an order total from Tally. A customer may need to supply an email once for Paystack hosted Checkout.
- A customer payment report becomes a **claim**. Paystack transaction verification or a valid independent sandbox payment event is required before Tally confirms payment. A screenshot, CSV, manual statement or Notion row never proves settlement.
- Operators can progress **paid** orders. Pickup: `confirmed → preparing → ready_for_pickup → fulfilled`; delivery: `confirmed → preparing → dispatched → delivery_reported → fulfilled`. Customer collection/receipt is confirmed in Shop; a dispute opens a support case. Explicit offline customer confirmation can be audited by staff. Stock is deducted once at fulfilment.
- Desk's catch-up summarizes reconciliation, orders, stock alerts, fulfilment and support based on ledger records. Admins can edit inventory and catalogue; Operators may read and progress paid orders but may not change prices or self-authorize payments.
- When a complaint needs human judgment, Shop opens a case for Desk. A recorded staff reply can be retrieved by that customer in Shop. **An internal reply is not proof of WhatsApp delivery or a native human takeover.**

## What is and is not proven

The latest dated implementation record reports **62 passing source and deployed Python tests**, sandbox health OK, **7 Shop / 11 Desk tools**, and real Notion OAuth write/readback on an earlier test setup. A protected reset on 14 November removed the ASYAN merchant connection and generated Notion pages while preserving merchant-authored source pages; the merchant was ready for clean re-registration. The founder reports the final simulator video has been recorded. **This document has not independently inspected that recording**, so final recorded Paystack/Notion transactions and native handoff should be described only if they are visible in playback and trace evidence.

Before any live customer launch, provide provider-attested WhatsApp sender identity, production payment/provider monitoring and reconciliation, backups and recoverability, consent/retention policy, incident management, operator escalation and confirmed outbound delivery/handoff. Tally currently refuses non-sandbox mode. Never use live keys or actual customers for this assessment.

**Merchant next action:** Review product prices, availability, fulfilment rules and support contacts in Desk, and keep the private provider setup links and keys off chat. Refer to `docs/PROVIDER_CONNECTIONS.md` and `docs/DEPLOYMENT_FIELD_NOTES.md` for technical evidence.
