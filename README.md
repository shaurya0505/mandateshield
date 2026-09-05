# MandateShield

> **Intelligent recovery for recurring payments — knowing not only when to retry, but when NOT to.**

MandateShield is an autonomous revenue recovery engine and safety guardian designed for recurring payments and subscription mandates in India (UPI AutoPay, Card Mandates, e-NACH).

Instead of blindly retrying failed debits on fixed schedules, MandateShield combines **context-aware strategy planning** with a strict **deterministic Policy Guardian** to determine whether a failed payment should be retried, delayed to coincide with observed historical payment timing, routed through an alternative active mandate, nudged, escalated to concierge operations, or stopped.

---

## 🛡️ Core Product Invariant

$$\textbf{AI Proposes.} \quad \longrightarrow \quad \textbf{Policy Guardian Authorizes.} \quad \longrightarrow \quad \textbf{Executor Verifies & Dispatches.}$$

- **No AI direct execution:** LLM models output purely advisory `StrategyProposal` records. AI models are **never** given credentials or authority to debit bank accounts.
- **Strict Deterministic Policy Guardian:** Evaluates 9 deterministic financial, regulatory, provider, and merchant safety rules. Only an approved evaluation issues a cryptographically bound `PolicyAuthorization` token.
- **Pure Integer Paisa Financials:** All transactions, risk calculations, and operational fees use integer paisa arithmetic (₹1 = 100 paisa) to eliminate floating-point drift.

---

## 🚀 Quickstart: Launching the Command Center

### 1. Requirements & Setup
```bash
# Clone the repository
git clone https://github.com/shaurya0505/mandateshield.git
cd mandateshield

# Install dependencies (FastAPI, uvicorn, pydantic, etc.)
pip install -r requirements.txt
```

### 2. Launch the Application
```bash
python run.py
# Or: uvicorn api.main:app --reload --port 8000
```
Open your browser and navigate to: **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

### 3. Run the Automated Test Suite (112 Passing Tests)
```bash
py -m pytest tests/unit tests/integration -v
```

---

## 🖥️ Command Center Live Demos

The MandateShield Command Center UI provides interactive, real-time visual demonstration of the entire intelligence pipeline:

### 1. Hero Flow: Historical Payment Timing Recovery
- **Customer:** Rahul Mehta | Subscription: ₹4,999.00 / month
- **Failure:** `INSUFFICIENT_FUNDS` on August 28, 2026.
- **Timing Signal:** Historical successful payment timing detected around Day 1–2.
- **AI Proposal:** `WAIT_AND_RETRY` (Delay 4 days / 345,600s to September 1, 2026).
- **Policy Guardian:** Evaluates rules $\rightarrow$ **APPROVED** $\rightarrow$ Issues authorization token.
- **Execution & Settlement:** Case held in `RECOVERY_SCHEDULED` (0 debits), clock advances to Sept 1, scheduled debit dispatches $\rightarrow$ Webhook HMAC verified $\rightarrow$ Case settled to **`RECOVERED`**.

### 2. Safety Guardian: AI Blocked on Revoked Mandate
- **Customer:** Deepa Rao | Mandate: `REVOKED` by customer on bank app | Amount: ₹999.00.
- **Unsafe AI Proposal:** Simulated aggressive AI proposes `RETRY_NOW` (95% confidence).
- **Policy Guardian:** Intercepts proposal $\rightarrow$ `RULE-PROV-01` (Mandate must be active) fails $\rightarrow$ **BLOCKED**.
- **Financial Result:** **₹0 debited**, customer protected from harassment and unnecessary simulated retry costs, case safely moved to **`STOPPED`**.

### 3. Webhook Resilience & Duplicate Protection
- **Resilience:** Gateway socket drop (504 Timeout) moves case to `ESCALATED` (`AMBIGUOUS_TIMEOUT`) to prevent blind duplicate debits.
- **Reconciliation:** Asynchronous `payment.captured` webhook arrives $\rightarrow$ HMAC verified $\rightarrow$ correlated $\rightarrow$ settled to `RECOVERED`.
- **Duplicate Protection:** Replaying the identical webhook is detected by `provider_event_id` $\rightarrow$ **`DUPLICATE_IGNORED`** (₹0 double counted).

### 4. Benchmark Lift & Counterfactual Evaluation (Milestone 9)
- Evaluates 20 balanced synthetic failure scenarios under 3 paired policies:
  1. `NO_RECOVERY` (Zero intervention baseline)
  2. `FIXED_RETRY` (Deterministic Fixed-Retry Baseline — schedule up to 3 attempts)
  3. `MANDATESHIELD` (Context-aware AI + Policy Guardian)
- Computes Gross Recovery, Net Recovery (after fees), Value-Weighted Rate, Customer Contact/Harassment Index, and Unnecessary Retries Avoided.

---

## 🏛️ System Architecture

```text
       Incoming Failure Event (e.g. INSUFFICIENT_FUNDS)
                             │
                             ▼
                   [FailureNormalizer]
                 (Canonical Failure Mode)
                             │
                             ▼
                   [RevenueRiskEngine]
           (Exposure in Paisa & Priority Score)
                             │
                             ▼
               [HistoricalTimingExtractor]
              (Day-of-Month Timing Cluster)
                             │
                             ▼
                     [RecoveryContext]
               (Immutable Factual Envelope)
                             │
                             ▼
                  [AI Strategy Planner]
                (Proposes StrategyProposal)
                             │
                     [SAFETY BARRIER]
                             │
                             ▼
                    [PolicyGuardian]
        (Enforces Merchant, Provider & Legal Rules)
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
             [ APPROVED ]          [ BLOCKED ]
                  │                     │
                  ▼                     ▼
         [PolicyAuthorization]     [Safe Stop]
                  │
                  ▼
          [RecoveryExecutor]
         (PaymentProvider Call)
                  │
                  ▼
          [WebhookReconciler]
         (HMAC Verification &
         Asynchronous Settlement)
                  │
                  ▼
            [ RECOVERED ]
```

---

## ⚖️ Fintech & Regulatory Clarifications

1. **Regulatory Precision:** Mandatory 24h retry cooldowns and 3-retry caps are modeled as **`MERCHANT_POLICY`**, not regulatory statutes.
2. **Timing Signals:** MandateShield does **not** claim knowledge of external customer salary or employer payroll dates. Signals are strictly derived from observed historical payment timestamps (`HISTORICAL_PAYMENT_WINDOW`).
3. **AI Confidence vs Calibrated Probability:** `StrategyProposal.strategy_confidence` is purely model self-reported confidence, **never** treated as a statistical debt collection probability.
4. **Synthetic Counterfactuals:** Benchmark lift metrics represent paired simulation differences under controlled failure models, not real-world causal econometric claims.

---

## 📜 Repository Structure

```text
MandateShield/
├── api/                     # FastAPI backend & demo orchestration services
│   ├── main.py              # Application entry point & static file routing
│   ├── routes.py            # REST endpoints for Command Center
│   └── demo_service.py      # Real domain service orchestration for interactive demos
├── domain/                  # Framework-independent domain core
│   ├── models/              # Immutable Pydantic models (Customer, Mandate, Case, Events)
│   ├── states/              # RecoveryState finite state machine
│   └── interfaces/          # Provider & Strategy Planner abstractions
├── infrastructure/          # Simulation & Security Infrastructure
│   ├── simulation/          # SimulatedPaymentProvider, SimulationClock, ScenarioGenerator
│   └── security/            # SimulatedWebhookVerifier (HMAC-SHA256 verification)
├── services/                # Pure domain services
│   ├── ingestion/           # FailureNormalizer
│   ├── risk/                # RevenueRiskEngine
│   ├── signals/             # HistoricalTimingExtractor & RecoveryContextBuilder
│   ├── ai/                  # GeminiStrategyPlanner & DeterministicFallbackPlanner
│   ├── policy/              # PolicyGuardian (9 deterministic rules)
│   ├── executor/            # RecoveryExecutor (In-process idempotency & dispatch)
│   ├── reconciliation/      # WebhookReconciler (Deduplication & async settlement)
│   └── evaluation/          # BatchEvaluator, ScenarioRunner, MetricsCalculator
├── ui/                      # Fintech Command Center Frontend
│   ├── index.html           # Command Center single-page dashboard
│   ├── app.js               # Client-side telemetry & demo controllers
│   └── styles.css           # Custom fintech dark theme stylesheet
├── tests/                   # 112 automated unit and integration tests
└── run.py                   # Single-command server launcher
```
