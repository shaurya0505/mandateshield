# Razorpay Integration & Mapping Reference

This document serves as the single source of truth for distinguishing **verified official Razorpay behavior** from **internal simulation assumptions** and **merchant policy layers**.

---

## 1. Verified Official Razorpay Concepts & Webhooks

The following entities and events are aligned with official Razorpay documentation (Subscriptions, Payment Links, Orders, and Smart Collect / Invoices):

### 1.1 Webhook Events (Official)
- `subscription.charged` — Triggered when an automated recurring subscription charge succeeds.
- `subscription.pending` — Triggered when a subscription charge is pending authentication/processing.
- `subscription.halted` — Triggered when max retries are exhausted or mandate cannot be charged.
- `subscription.cancelled` — Triggered when a subscription is cancelled.
- `payment.authorized` — Triggered when a payment attempt is authorized.
- `payment.failed` — Triggered when a recurring or one-time payment attempt fails.
- `payment.captured` — Triggered when an authorized payment is successfully captured.

### 1.2 Mandate / Subscription State Lifecycle (Official Razorpay)
- `created` — Subscription created, mandate registration pending.
- `authenticated` — Customer authenticated the e-mandate / UPI AutoPay authorization.
- `active` — Mandate active and recurring debits can be initiated.
- `pending` — Debit initiated, awaiting banking rail settlement confirmation.
- `halted` — Failed debits reached retry threshold, automated retries stopped by provider.
- `cancelled` — Explicitly cancelled by customer or merchant.
- `completed` — All billing cycles fulfilled.

### 1.3 Official Error Codes (Subset for Recurring Payments)
- `BAD_REQUEST_ERROR` / `GATEWAY_ERROR`
- `payment_failed` with sub-reasons:
  - `insufficient_funds`
  - `issuer_down` / `bank_technical_error`
  - `customer_declined`
  - `mandate_inactive` / `mandate_cancelled`
  - `authentication_failed`
  - `exceeded_limit`

---

## 2. Simulated Provider Extensions & Internal Domain Concepts

The following concepts are **internal abstractions** designed for MandateShield's simulation and intelligence platform:

| Concept / Action | Classification | Description |
|---|---|---|
| `PaymentProvider` Interface | **Internal Abstraction** | Generic interface allowing pluggable payment backends (`SimulatedPaymentProvider`, `RazorpayTestProvider`). |
| `WAIT_AND_RETRY` | **Simulation & Merchant Strategy** | Merchant-side intelligent scheduling before triggering Razorpay's charge API. |
| `SWITCH_PAYMENT_PATH` | **Simulation & Merchant Strategy** | Attempting recovery across alternate verified mandate tokens or payment methods attached to the customer account. |
| `GENERATE_PAYMENT_LINK` | **Razorpay Feature / Simulated Action** | Generating a standard Razorpay Payment Link (`POST /v1/payment_links`) as an alternative payment vector. |
| `SEND_RECOVERY_NUDGE` | **Internal Merchant Action** | Merchant-side customer communication (SMS, WhatsApp, Email) referencing the pending subscription. |
| `HISTORICAL_PAYMENT_WINDOW` | **Internal Feature Signal** | Derived purely from merchant historical transaction timestamps; does not assume or inspect external salary/banking data. |
| `PolicyAuthorization` | **Internal Security Record** | Deterministic domain record verifying policy checks before dispatching any payment action. |

---

## 3. Regulatory vs Provider vs Merchant Boundaries

1. **`REGULATORY_REQUIREMENT`**: Mandated by official directives (e.g., RBI e-mandate pre-debit notifications requirement 24h prior, AFA requirement for registration).
2. **`PROVIDER_RULE`**: Constraints enforced directly by Razorpay (e.g., maximum charge amount registered on mandate, API rate limits, valid mandate token states).
3. **`MERCHANT_POLICY`**: Configurable business rules enforced by MandateShield (e.g., max 3 recovery attempts, 24h cooldown, VIP threshold > ₹25,000).
4. **`SIMULATION_POLICY`**: Synthetic environment definitions (e.g., simulated cost metrics, mock clock advancement).
