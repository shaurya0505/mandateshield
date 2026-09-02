# MandateShield

> **Intelligent recovery for recurring payments — knowing not only when to retry, but when NOT to.**

MandateShield is a payment-recovery system designed for recurring payments and mandates.

Instead of blindly retrying failed payments, MandateShield combines a **deterministic financial safety layer** with a **contextual AI strategy planner** to determine whether a failed payment should be retried, delayed, routed through another payment path, nudged, escalated, or stopped.

The core principle is simple:

> **AI proposes. Deterministic systems authorize.**

---

## 🚧 Project Status

MandateShield is currently under active development as part of the **Razorpay Buildathon — AI Revenue Recovery** track.

### Completed

- [x] Domain entities and financial models
- [x] Paisa-level integer arithmetic
- [x] Recovery state machine
- [x] Deterministic policy authorization model
- [x] Immutable domain events
- [x] Payment provider abstraction
- [x] Deterministic simulation clock
- [x] Seeded synthetic payment provider
- [x] Synthetic banking failure scenarios
- [x] Payment idempotency simulation
- [x] 20 unit tests passing

### In Progress

- [ ] Failure normalization
- [ ] Revenue-at-risk engine
- [ ] Recovery signal aggregation
- [ ] Contextual AI strategy planner
- [ ] Deterministic Policy Guardian
- [ ] Recovery execution workflow
- [ ] Batch recovery evaluation
- [ ] Chaos/failure testing
- [ ] Operations dashboard

---

# The Problem

Recurring-payment businesses lose revenue when otherwise recoverable payments fail.

A failed payment does **not** always mean the same thing.

For example:

```text
Payment Failure
      │
      ├── Insufficient funds
      │
      ├── Temporary bank failure
      │
      ├── Payment rail degradation
      │
      ├── Mandate inactive/revoked
      │
      ├── Authentication friction
      │
      └── Unknown / unsafe condition
```

A naive recovery system might respond to all of them with:

```text
PAYMENT FAILED
      ↓
RETRY
      ↓
RETRY
      ↓
RETRY
      ↓
STOP
```

This can result in:

- unnecessary retries
- poor customer experience
- wasted recovery attempts
- recovery attempts at the wrong time
- avoidable operational costs
- insufficient auditability

MandateShield takes a different approach.

---

# The MandateShield Approach

MandateShield evaluates the context surrounding a payment failure before deciding what should happen next.

It considers signals such as:

- failure category
- historical payment behavior
- payment timing patterns
- mandate status
- retry history
- payment rail health
- issuer/bank behavior
- transaction amount
- customer/recovery context

The system can then select from a bounded set of recovery actions:

```text
RETRY_NOW
WAIT_AND_RETRY
SWITCH_PAYMENT_PATH
GENERATE_PAYMENT_LINK
SEND_RECOVERY_NUDGE
ESCALATE_TO_HUMAN
STOP_RECOVERY
```

Importantly, **"do nothing right now" is a valid recovery decision.**

For example:

```text
Aug 28
₹4,999 recurring payment
        │
        ▼
INSUFFICIENT_FUNDS
        │
        ▼
Historical successful payments:
Aug 2
Jul 1
Jun 3
        │
        ▼
Detected historical payment window
        │
        ▼
AI strategy proposal:
WAIT_AND_RETRY
        │
        ▼
Deterministic Policy Guardian
        │
        ▼
AUTHORIZED
        │
        ▼
Retry at permitted time
```

The AI does not directly charge the customer.

---

# Architecture

```text
                         ┌──────────────────────┐
                         │   Payment Provider   │
                         │ Razorpay / Simulator │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Payment Failure     │
                         │      Event           │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Failure Normalizer   │
                         │                      │
                         │ Provider error       │
                         │        ↓             │
                         │ Canonical category   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Revenue Risk /      │
                         │  Context Engine      │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  AI Strategy Planner │
                         │                      │
                         │ Contextual reasoning │
                         │ Bounded action       │
                         │ Confidence           │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Policy Guardian     │
                         │                      │
                         │ Retry limits         │
                         │ Cooldowns            │
                         │ Mandate limits       │
                         │ Provider rules       │
                         │ Merchant policies    │
                         └──────────┬───────────┘
                                    │
                              ┌─────┴─────┐
                              │           │
                           BLOCK       APPROVE
                              │           │
                              │           ▼
                              │  ┌──────────────────┐
                              │  │ Recovery         │
                              │  │ Executor         │
                              │  └────────┬─────────┘
                              │           │
                              │           ▼
                              │  ┌──────────────────┐
                              │  │ Payment Provider │
                              │  └────────┬─────────┘
                              │           │
                              └─────┬─────┘
                                    ▼
                         ┌──────────────────────┐
                         │ Audit / Recovery     │
                         │ Outcome              │
                         └──────────────────────┘
```

---

# Safety Architecture

MandateShield follows a **fail-closed architecture**.

The AI is intentionally prevented from controlling critical financial operations.

| Responsibility | System |
|---|---|
| State transitions | Deterministic |
| Financial arithmetic | Deterministic |
| Currency representation | Integer paisa |
| Retry limits | Deterministic |
| Mandate limits | Deterministic |
| Idempotency | Deterministic |
| Authorization | Deterministic |
| Policy enforcement | Deterministic |
| Audit records | Deterministic |
| Failure normalization | Deterministic |
| Contextual strategy | AI |
| Recovery action proposal | AI |
| Confidence/reasoning | AI |

### Core principle

```text
                    AI
                     │
                     │ proposes
                     ▼
             ┌───────────────┐
             │ Bounded Action│
             │    Space      │
             └───────┬───────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  Policy Guardian    │
          │                     │
          │ deterministic       │
          │ authorization       │
          └──────────┬──────────┘
                     │
              ┌──────┴──────┐
              │             │
            BLOCK         APPROVE
              │             │
              ▼             ▼
             STOP         EXECUTE
```

An invalid or unavailable AI response must **never bypass deterministic controls**.

---

# Financial Safety

MandateShield uses integer arithmetic at the domain layer.

Amounts are represented in **paisa**, not floating-point rupees.

```python
amount_in_paisa = 499900
```

This avoids floating-point rounding problems in financial calculations.

The domain also enforces:

- positive mandate/subscription amounts
- valid state transitions
- terminal state protection
- mandate limits
- deterministic authorization
- idempotent payment operations

---

# State Machine

Recovery cases move through explicit states rather than arbitrary status changes.

```text
PAYMENT_FAILED
      │
      ▼
ANALYZING
      │
      ▼
STRATEGY_PROPOSED
      │
      ▼
POLICY_EVALUATED
      │
      ├───────────────┐
      │               │
   APPROVED         BLOCKED
      │               │
      ▼               ▼
RECOVERY_ATTEMPTED  STOPPED
      │
      ├───────────────┐
      │               │
      ▼               ▼
  RECOVERED       RECOVERY_FAILED
```

Recovery execution requires deterministic policy authorization.

Terminal states cannot be reactivated.

---

# Synthetic Payment Simulator

MandateShield includes a deterministic synthetic payment provider for development and evaluation.

The simulator models conditions such as:

- insufficient funds
- transient issuer failures
- bank technical errors
- payment rail degradation
- inactive/revoked mandates
- mandate amount limits
- successful recovery
- duplicate payment attempts

The simulator uses:

- seeded randomness
- deterministic virtual time
- reproducible scenarios
- provider-level idempotency caching

This allows identical experiments to be replayed and audited.

### Important design boundary

The simulator models the **environment**.

It does not decide how the recovery system should respond.

```text
Simulator
    │
    │ produces
    ▼
Payment Outcome
    │
    ▼
Recovery Intelligence
    │
    │ decides
    ▼
Recovery Strategy
```

---

# Provider Abstraction

The recovery system interacts with a generic `PaymentProvider` interface.

```text
                 PaymentProvider
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
   SimulatedPaymentProvider   Future Provider
              │
              ▼
       Synthetic banking
          environment
```

This keeps provider-specific infrastructure separate from the financial domain.

Razorpay-specific concepts and mappings are documented separately in:

```text
docs/RAZORPAY_MAPPING.md
```

---

# Rule Provenance

Financial and operational rules are explicitly categorized.

```text
REGULATORY_REQUIREMENT
PROVIDER_RULE
MERCHANT_POLICY
SIMULATION_POLICY
```

This prevents simulation assumptions or merchant policies from being presented as regulatory requirements.

Every future policy decision should preserve its provenance.

---

# Testing

Current test suite:

```text
20 passed
```

Tests currently cover:

### Domain

- customer validation
- mandate validation
- subscription validation
- recovery-case calculations
- policy authorization
- immutable domain events
- state-machine transitions
- unauthorized recovery prevention
- terminal-state protection
- illegal transitions

### Simulator

- virtual clock behavior
- deterministic replay
- liquidity timing scenarios
- transient issuer failures
- rail degradation
- revoked mandates
- mandate limits
- provider idempotency
- payment-link generation

Run the tests with:

```bash
py -m pytest tests/unit -v
```

---

# Project Structure

```text
mandateshield/
│
├── docs/
│   └── RAZORPAY_MAPPING.md
│
├── domain/
│   ├── events/
│   ├── interfaces/
│   ├── models/
│   ├── policies/
│   └── states/
│
├── infrastructure/
│   └── simulation/
│
├── services/
│
├── tests/
│   └── unit/
│
├── .env.example
├── .gitignore
└── requirements.txt
```

The project follows a separation between:

```text
Domain
   ↓
Application / Services
   ↓
Infrastructure
```

The domain layer remains independent of external frameworks wherever practical.

---

# Development Roadmap

MandateShield is being developed in vertical slices.

## Slice 1 — Financial Core

- [x] Domain models
- [x] State machine
- [x] Domain events
- [x] Policy authorization model
- [x] Payment provider abstraction
- [x] Synthetic payment simulator
- [ ] Failure normalization
- [ ] Revenue risk engine
- [ ] Slice 1 integration test

## Slice 2 — Recovery Intelligence

- [ ] Recovery signal aggregation
- [ ] Customer/payment context builder
- [ ] Historical payment timing signals
- [ ] Recovery strategy model
- [ ] Contextual AI strategy planner

## Slice 3 — Safe Execution

- [ ] Policy Guardian
- [ ] Recovery executor
- [ ] Idempotent execution
- [ ] Audit ledger
- [ ] Recovery outcome tracking

## Slice 4 — Evaluation & Operations

- [ ] Baseline recovery strategy
- [ ] MandateShield strategy
- [ ] Batch simulation
- [ ] Recovery lift metrics
- [ ] Chaos Lab
- [ ] Operations dashboard
- [ ] End-to-end demo

---

# Evaluation Strategy

MandateShield will eventually be evaluated against recovery baselines rather than only individual examples.

The planned comparison is:

```text
                    Payment Failures
                           │
             ┌─────────────┼─────────────┐
             │             │             │
             ▼             ▼             ▼
        No Recovery    Fixed Retry   MandateShield
                                      │
                                      ▼
                               Contextual Strategy
```

Key metrics will include:

- gross recovery
- net recovery
- recovery rate
- recovery lift vs no recovery
- recovery lift vs fixed retry
- unnecessary recovery attempts
- notification/harassment rate
- recovery cost
- policy violations blocked

The goal is not simply to maximize retries.

The goal is to maximize **safe, economically meaningful recovery**.

---

# Why AI?

MandateShield does not use an LLM for deterministic financial rules.

The AI layer is useful where contextual reasoning is required.

For example:

```text
Failure:
INSUFFICIENT_FUNDS

Context:
- historically successful subscription
- recurring payment timing pattern
- recent failure
- healthy payment rail
- retry history within policy
- customer value context
```

The AI can use these signals to propose:

```text
WAIT_AND_RETRY
```

with structured reasoning and confidence.

The deterministic layer then decides whether that action is actually permitted.

---

# Design Philosophy

MandateShield is built around five principles:

### 1. AI proposes, deterministic systems authorize

No LLM response can directly bypass financial controls.

### 2. Recovery does not always mean retry

Sometimes the optimal action is to wait, switch paths, escalate, or stop.

### 3. Financial correctness comes before AI sophistication

State, money, authorization, idempotency, and policy enforcement remain deterministic.

### 4. Every decision should be explainable

Recovery decisions should preserve the context, proposed action, policy evaluation, and eventual outcome.

### 5. Simulation before production integration

The system is developed against a deterministic synthetic environment before any live-provider integration is considered.

---

# Tech Stack

### Backend

- Python
- FastAPI
- Pydantic
- PostgreSQL
- SQLAlchemy

### AI

- Google Gemini
- Structured JSON strategy outputs

### Frontend

- Next.js
- React
- TypeScript

### Testing

- Pytest
- Property-based testing where appropriate

### Infrastructure

- Synthetic payment provider
- Deterministic simulation clock
- Provider abstraction

---

# Current Focus

The current development focus is:

> **Failure Normalization + Revenue Risk Engine**

The next milestone will transform raw provider outcomes into canonical financial failure categories and calculate deterministic revenue-at-risk and recovery priority.

---

# Disclaimer

MandateShield is a **synthetic research and hackathon project**.

Payment behavior, banking conditions, recovery outcomes, and customer data used in simulations are synthetic.

Provider-specific behavior is implemented only where documented or explicitly marked as simulation behavior.

This project is not intended to initiate real customer charges without appropriate production controls, provider integration, compliance review, and authorization.

---

## Author

**Shaurya Agarwal**

Built as part of the **Razorpay Buildathon — AI Revenue Recovery** track.
