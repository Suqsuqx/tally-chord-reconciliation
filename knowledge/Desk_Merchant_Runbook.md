# Tally Desk — Generic Merchant Operations Runbook (Sandbox)

**Audience:** Authenticated Admin and Operator test staff. **Source type:** Operational guidance, not the live ledger.

- Admin can manage product name, price, available stock and warning threshold. Operator can manage paid-order fulfilment and customer support but cannot edit product prices or stock counts.
- Product stock available for new orders = on-hand quantity minus units reserved for existing orders. Quantity and price must come from Tally tools.
- “Paid” is not a verbal status. Customer-reported transfer is a claim only. A signed provider event is checked for event uniqueness, order reference, currency and amount. Mismatches appear as reconciliation exceptions.
- A catch-up should lead with verified matched receipts, unpaid orders, unmatched/mismatched events, low stock, complaints and pending staff decisions. Cite actual tool figures only.
- If stock is low, warn with product name, available quantity and threshold. Physical recounts are staff-reported adjustments with a reason and audit record; do not claim independent warehouse verification.
- Staff may reply to individual support cases. Do not automatically copy customer-specific responses into reusable policies.
- A native human takeover of the customer's Chord thread is different from writing a case response via Desk. When supported, staff should return control to Shop after resolution; overdue unanswered cases remain visible in catch-up.
- All payment keys, messages and identities are sandbox-only. Never use a real merchant's credentials, customer phone number or live payments in the exercise.
