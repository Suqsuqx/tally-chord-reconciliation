# Tally Merchant Go-Live Note — Assessment Sandbox

Tally Shop receives customer product questions, orders, payment reports and complaints through a simulated WhatsApp-style channel. Tally Desk gives authorized staff a view of orders, provider-verified matched payments, payment exceptions, inventory warnings and customer issues. Prices, payment status and stock come from the merchant ledger; Tally will never confirm payment from a customer’s screenshot or statement alone.

An Admin maintains the catalogue, prices, physical stock and alert thresholds. Operators can inspect operations, respond to customer cases and advance only paid orders from preparing to fulfilled. Every private action uses a short-lived sandbox actor session and backend role checks. A teammate name, chat link or claim to be the owner does not grant staff access.

When a question needs merchant judgment, Tally creates a case and can request human help. A staff reply stored in a case is not proof that the customer received it. Native takeover, direct outbound delivery and hand-back must be verified in the selected channel; until then, customers retrieve approved case replies through Tally Shop.

This assessment uses fictitious actors, test merchant records and sandbox payment verification. Before serving real customers, the merchant needs provider-signed WhatsApp identity binding, production payment-provider verification, managed secret rotation, database backups and monitoring, an agreed returns/delivery policy, named staff ownership of escalations, tested outbound delivery/failure alerts, privacy/retention controls and incident procedures. The current server deliberately refuses non-sandbox mode. No production payment, identity or WhatsApp capability is implied by this demonstration.
