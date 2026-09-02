import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Dict, List, Tuple
from domain.interfaces.payment_provider import (
    PaymentProvider,
    ProviderPaymentResult,
    ProviderPaymentLinkResult,
    ProviderMandateStatusResult,
    RailHealthMetrics,
)
from domain.models.mandate import Mandate, MandateStatus, PaymentMethod, IssuerBank
from infrastructure.simulation.simulation_clock import SimulationClock


class SimulatedPaymentProvider(PaymentProvider):
    """
    Deterministic Synthetic Payment Provider for simulated recurring transactions.
    Supports reproducible seeded randomness, temporal liquidity windows,
    rail degradation injection, and transient network/issuer faults.
    """

    # Baseline success rates by issuer bank under normal conditions
    BASELINE_BANK_SUCCESS_RATES: Dict[IssuerBank, float] = {
        IssuerBank.HDFC: 0.94,
        IssuerBank.ICICI: 0.92,
        IssuerBank.SBI: 0.88,
        IssuerBank.AXIS: 0.90,
        IssuerBank.KOTAK: 0.89,
        IssuerBank.YES: 0.85,
        IssuerBank.OTHER: 0.80,
    }

    def __init__(self, clock: Optional[SimulationClock] = None, seed: int = 42):
        self.clock = clock or SimulationClock()
        self.seed = seed
        self._rng = random.Random(seed)
        
        # In-memory simulated registries
        self._mandates: Dict[str, Mandate] = {}
        self._liquidity_windows: Dict[str, Tuple[int, int]] = {}  # mandate_token -> (start_day, end_day)
        self._forced_outcomes: Dict[str, ProviderPaymentResult] = {}  # mandate_token -> forced result
        self._transient_glitches: Dict[str, int] = {}  # mandate_token -> count of transient failures remaining
        self._rail_outages: List[Dict[str, Any]] = []  # active/scheduled rail degradations
        self._attempt_ledger: List[Dict[str, Any]] = []  # recorded simulation attempts for stats
        self._processed_idempotency_keys: Dict[str, ProviderPaymentResult] = {}

    def register_mandate(
        self,
        mandate: Mandate,
        liquidity_window_days: Optional[Tuple[int, int]] = (1, 4),
    ) -> None:
        """Registers a synthetic mandate and its historical liquidity window (day-of-month cluster)."""
        self._mandates[mandate.provider_mandate_token] = mandate
        if liquidity_window_days:
            self._liquidity_windows[mandate.provider_mandate_token] = liquidity_window_days

    def force_next_outcome(self, mandate_token: str, result: ProviderPaymentResult) -> None:
        """Forces an exact outcome for the next charge attempt on a mandate."""
        self._forced_outcomes[mandate_token] = result

    def inject_transient_glitch(self, mandate_token: str, fail_count: int = 1) -> None:
        """Configures a mandate to fail with a transient issuer error for N attempts before succeeding."""
        self._transient_glitches[mandate_token] = fail_count

    def inject_rail_degradation(
        self,
        issuer_bank: IssuerBank,
        payment_method: PaymentMethod,
        start_time: datetime,
        duration_hours: int,
        degraded_success_rate: float = 0.25,
    ) -> None:
        """Injects a time-bounded rail degradation episode."""
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        end_time = start_time + timedelta(hours=duration_hours)
        self._rail_outages.append({
            "issuer_bank": issuer_bank,
            "payment_method": payment_method,
            "start_time": start_time,
            "end_time": end_time,
            "degraded_success_rate": degraded_success_rate,
        })

    def charge_mandate(
        self,
        mandate_token: str,
        amount_in_paisa: int,
        idempotency_key: str,
        attempt_context: Optional[dict[str, Any]] = None,
    ) -> ProviderPaymentResult:
        """Executes a simulated recurring debit attempt with deterministic behavior."""
        current_time = self.clock.now()

        # 1. Idempotency Check: Same key returns the exact identical prior result
        if idempotency_key in self._processed_idempotency_keys:
            return self._processed_idempotency_keys[idempotency_key]

        # 2. Mandate Existence & Validity
        mandate = self._mandates.get(mandate_token)
        if not mandate:
            result = ProviderPaymentResult(
                success=False,
                raw_error_code="BAD_REQUEST_ERROR",
                raw_error_message="Mandate token not found or invalid",
                settled_at=current_time,
            )
            self._processed_idempotency_keys[idempotency_key] = result
            return result

        if mandate.status != MandateStatus.ACTIVE:
            result = ProviderPaymentResult(
                success=False,
                raw_error_code="mandate_inactive",
                raw_error_message=f"Mandate is in {mandate.status.value} status and cannot be charged",
                settled_at=current_time,
            )
            self._record_attempt(mandate, result, current_time)
            self._processed_idempotency_keys[idempotency_key] = result
            return result

        if amount_in_paisa > mandate.max_amount_in_paisa:
            result = ProviderPaymentResult(
                success=False,
                raw_error_code="exceeded_limit",
                raw_error_message=f"Amount {amount_in_paisa} exceeds mandate max amount {mandate.max_amount_in_paisa}",
                settled_at=current_time,
            )
            self._record_attempt(mandate, result, current_time)
            self._processed_idempotency_keys[idempotency_key] = result
            return result

        # 3. Check Explicit Forced Outcomes
        if mandate_token in self._forced_outcomes:
            forced_result = self._forced_outcomes.pop(mandate_token)
            self._record_attempt(mandate, forced_result, current_time)
            self._processed_idempotency_keys[idempotency_key] = forced_result
            return forced_result

        # 4. Check Transient Glitches
        if self._transient_glitches.get(mandate_token, 0) > 0:
            self._transient_glitches[mandate_token] -= 1
            result = ProviderPaymentResult(
                success=False,
                raw_error_code="bank_technical_error",
                raw_error_message="Issuer bank temporary technical failure (503 Service Unavailable)",
                settled_at=current_time,
            )
            self._record_attempt(mandate, result, current_time)
            self._processed_idempotency_keys[idempotency_key] = result
            return result

        # 5. Check Rail Degradation Episodes
        active_degradation = self._get_active_rail_degradation(mandate.issuer_bank, mandate.payment_method, current_time)
        if active_degradation:
            roll = self._rng.random()
            if roll > active_degradation["degraded_success_rate"]:
                result = ProviderPaymentResult(
                    success=False,
                    raw_error_code="issuer_down",
                    raw_error_message=f"{mandate.issuer_bank.value} banking network is experiencing degraded connectivity",
                    settled_at=current_time,
                )
                self._record_attempt(mandate, result, current_time)
                self._processed_idempotency_keys[idempotency_key] = result
                return result

        # 6. Check Liquidity Timing Window
        window = self._liquidity_windows.get(mandate_token)
        if window:
            start_day, end_day = window
            current_day = current_time.day
            in_window = (start_day <= current_day <= end_day) if start_day <= end_day else (current_day >= start_day or current_day <= end_day)
            
            if not in_window:
                # Outside liquidity window, simulate high liquidity failure rate (85% fail)
                if self._rng.random() < 0.85:
                    result = ProviderPaymentResult(
                        success=False,
                        raw_error_code="insufficient_funds",
                        raw_error_message="Debit declined: Insufficient funds in customer account",
                        settled_at=current_time,
                    )
                    self._record_attempt(mandate, result, current_time)
                    self._processed_idempotency_keys[idempotency_key] = result
                    return result

        # 7. Baseline Bank Reliability Roll
        base_rate = self.BASELINE_BANK_SUCCESS_RATES.get(mandate.issuer_bank, 0.85)
        if self._rng.random() < base_rate:
            tx_id = f"pay_sim_{uuid.uuid4().hex[:12]}"
            result = ProviderPaymentResult(
                success=True,
                provider_tx_id=tx_id,
                settled_at=current_time,
            )
        else:
            result = ProviderPaymentResult(
                success=False,
                raw_error_code="bank_technical_error",
                raw_error_message="Issuer rail returned transient processing error",
                settled_at=current_time,
            )

        self._record_attempt(mandate, result, current_time)
        self._processed_idempotency_keys[idempotency_key] = result
        return result

    def generate_payment_link(
        self,
        amount_in_paisa: int,
        customer_id: str,
        description: str,
        expires_in_seconds: int = 86400,
    ) -> ProviderPaymentLinkResult:
        """Generates a synthetic payment link."""
        link_id = f"plink_sim_{uuid.uuid4().hex[:10]}"
        current_time = self.clock.now()
        expires_at = current_time + timedelta(seconds=expires_in_seconds)
        return ProviderPaymentLinkResult(
            link_id=link_id,
            short_url=f"https://rzp.io/i/{link_id}",
            status="active",
            expires_at=expires_at,
        )

    def verify_mandate(self, mandate_token: str) -> ProviderMandateStatusResult:
        """Queries the simulator for mandate status."""
        mandate = self._mandates.get(mandate_token)
        if not mandate:
            return ProviderMandateStatusResult(
                mandate_token=mandate_token,
                status=MandateStatus.EXPIRED,
                max_amount_in_paisa=0,
                is_active=False,
            )
        return ProviderMandateStatusResult(
            mandate_token=mandate_token,
            status=mandate.status,
            max_amount_in_paisa=mandate.max_amount_in_paisa,
            is_active=(mandate.status == MandateStatus.ACTIVE),
        )

    def get_rail_health(
        self,
        issuer_bank: IssuerBank,
        payment_method: PaymentMethod,
        window_minutes: int = 60,
    ) -> RailHealthMetrics:
        """Computes statistical success rate over recent attempts in the simulation clock window."""
        current_time = self.clock.now()
        window_start = current_time - timedelta(minutes=window_minutes)
        
        # Filter matching attempts in the time window
        recent_attempts = [
            att for att in self._attempt_ledger
            if att["issuer_bank"] == issuer_bank
            and att["payment_method"] == payment_method
            and window_start <= att["timestamp"] <= current_time
        ]

        active_degradation = self._get_active_rail_degradation(issuer_bank, payment_method, current_time)

        if len(recent_attempts) >= 5:
            total = len(recent_attempts)
            successes = sum(1 for att in recent_attempts if att["success"])
            rate = round(successes / total, 3)
            is_degraded = rate < 0.65 or active_degradation is not None
        else:
            # Not enough samples in window; use active degradation state or baseline
            if active_degradation:
                rate = active_degradation["degraded_success_rate"]
                is_degraded = True
                total = 0
                successes = 0
            else:
                rate = self.BASELINE_BANK_SUCCESS_RATES.get(issuer_bank, 0.85)
                is_degraded = False
                total = 0
                successes = 0

        return RailHealthMetrics(
            issuer_bank=issuer_bank,
            payment_method=payment_method,
            sample_window_minutes=window_minutes,
            total_attempts=total,
            successful_attempts=successes,
            success_rate=rate,
            is_degraded=is_degraded,
        )

    def _record_attempt(self, mandate: Mandate, result: ProviderPaymentResult, timestamp: datetime) -> None:
        self._attempt_ledger.append({
            "mandate_id": mandate.id,
            "issuer_bank": mandate.issuer_bank,
            "payment_method": mandate.payment_method,
            "success": result.success,
            "error_code": result.raw_error_code,
            "timestamp": timestamp,
        })

    def _get_active_rail_degradation(
        self, issuer_bank: IssuerBank, payment_method: PaymentMethod, current_time: datetime
    ) -> Optional[Dict[str, Any]]:
        for outage in self._rail_outages:
            if (
                outage["issuer_bank"] == issuer_bank
                and outage["payment_method"] == payment_method
                and outage["start_time"] <= current_time <= outage["end_time"]
            ):
                return outage
        return None
