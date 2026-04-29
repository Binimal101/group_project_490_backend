# Payment orchestration — Flow-level overview

This document describes how payment-related data and flows are modeled and orchestrated in the system. It focuses on runtime flows (what happens when a client saves a card, subscribes, is billed, or a charge fails) and the key database models involved.

## Key models

- `PaymentInformation` (`payment_information`)
  - Stores card fields: `ccnum`, `cv`, `exp_date`.
  - Pydantic validators run Luhn checks and basic format/expiry validation.
  - Referenced by `Client.payment_information_id`.

- `PricingPlan` (`pricing_plan`)
  - Owned by a coach (`coach_id`) and defines `payment_interval` (`monthly`/`yearly`) and `price_cents`.
  - `open_to_entry` determines whether new subscriptions may join.

- `Subscription` (`subscription`)
  - Links `client_id` to an optional `pricing_plan_id`.
  - Tracks `status` (`active`, `past_due`, `unpaid`, `canceled`), `start_date`, and `canceled_at`.

- `BillingCycle` (`billing_cycle`)
  - Represents a specific charge period for a subscription (has `entry_date`, `end_date`, `active`).
  - FK to `subscription` and `pricing_plan` so the record captures pricing and subscription context for that cycle.

- `Invoice` (`invoice`)
  - Tied to a `billing_cycle` and `client_id`.
  - Contains `amount` and `outstanding_balance`.

## High-level flows

1) Save payment method
   - Client POSTs card info → server validates (`PaymentInformation` validators include Luhn check) → store `PaymentInformation` row.
   - Link to client by setting `Client.payment_information_id`.

2) Subscribe a client to a coach plan
   - Create a `Subscription` (client_id + pricing_plan_id). Set `status = active`, `start_date`.
   - Scheduling systems (cron/background job) will create `BillingCycle` rows in advance or at time-of-charge.

3) Billing cycle creation and invoicing
   - For each active `Subscription`, a `BillingCycle` row is created for the period referencing the `Subscription` and `PricingPlan`.
   - An `Invoice` is then created for the `BillingCycle` and `client_id` with the calculated `amount`.

4) Attempting a charge
   - Payment processor uses the client's linked `PaymentInformation` to attempt charge for `Invoice.amount`.
   - On success: set `Invoice.outstanding_balance = 0` (or remove/mark paid), keep `Subscription.status = active`.
   - On failure: set `Invoice.outstanding_balance` appropriately and update `Subscription.status` to `past_due` or `unpaid` depending on retry policy.

5) Retries, past due handling, and cancellation
   - Retry policy is implemented by background jobs that attempt re-charges and update `Invoice`/`Subscription` status.
   - If unresolved, the system may set `canceled_at` and `Subscription.status = canceled`.

6) Termination / cleanup
   - When subscriptions/pricing plans or coaches are deleted, configured `ondelete` rules cascade or nullify related rows to maintain DB consistency.

## Example sequence (simplified)

1. Create `PaymentInformation` (id = 42).
2. Update `Client.payment_information_id = 42`.
3. Create `Subscription` (id = 10, client_id = 5, pricing_plan_id = 3).
4. Background job creates `BillingCycle` (id = 7) for the subscription period.
5. Create `Invoice` (billing_cycle_id = 7, client_id = 5, amount = 19.99).
6. Charge attempt: success → `Invoice.outstanding_balance = 0`; failure → `Invoice.outstanding_balance = 19.99`, `Subscription.status = past_due`.

## Implementation notes and caveats

- `PricingPlan.price_cents` uses integer cents; convert to dollars (`price_cents / 100`) when populating `Invoice.amount`.
- `Invoice.amount` is a float in the schema; be careful with rounding and conversions.
- `PaymentInformation` stores raw card data in the DB schema. This is NOT PCI-compliant in production. Prefer tokenization (use processor tokens) in real deployments.
- Validators in `PaymentInformation` use `luhn_sum` (see `src/database/payment/services.py`) to catch invalid card numbers early.
- The codebase relies on background jobs/cron to create `BillingCycle` and process charges. Ensure those jobs run in a single transaction where possible to avoid inconsistent state (create invoice + attempt charge atomically where feasible).

## Where to look in code

- Model definitions: `src/database/payment/models.py`
- Luhn helper: `src/database/payment/services.py`
- Client link: `src/database/client/models.py` (`payment_information_id`)
- Billing/business logic and jobs: search for `Subscription`, `BillingCycle`, and `Invoice` usage in `src/` to find billing processors and scheduled tasks.

## Next steps (optional)

- Add an example sequence showing code-level calls (service functions / endpoint names) that create subscriptions and invoices.
- Add a short diagram showing the lifecycle from `Subscription` → `BillingCycle` → `Invoice` → charge attempt → status transitions.

---
Generated: concise payment orchestration flow for the repo.
