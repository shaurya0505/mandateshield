from datetime import datetime, timezone
from typing import Optional, Dict
from pydantic import BaseModel, Field
from domain.models.payment_attempt import FailureCategory


class NormalizedFailure(BaseModel):
    """
    Deterministic normalization outcome for raw provider error codes.
    Maintains full auditability by preserving raw error strings and provenance.
    """
    raw_error_code: str
    raw_error_message: Optional[str] = None
    category: FailureCategory
    is_retryable_by_nature: bool
    provenance: str = Field(default="SIMULATED_PROVIDER")
    normalized_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FailureNormalizer:
    """
    Normalizes diverse, unstructured, or provider-specific failure codes
    into the canonical MandateShield FailureCategory domain enum.
    """

    # Direct canonical lookup table for verified provider error codes
    _EXACT_CODE_MAPPING: Dict[str, FailureCategory] = {
        # Liquidity Errors
        "insufficient_funds": FailureCategory.LIQUIDITY_FAILURE,
        "bad_request_insufficient_funds": FailureCategory.LIQUIDITY_FAILURE,
        "low_balance": FailureCategory.LIQUIDITY_FAILURE,
        "account_funds_low": FailureCategory.LIQUIDITY_FAILURE,
        
        # Transient Bank / Issuer Glitches
        "bank_technical_error": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "issuer_down": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "internal_server_error": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "service_unavailable": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "gateway_error": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "503": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "502": FailureCategory.TRANSIENT_ISSUER_FAILURE,
        "500": FailureCategory.TRANSIENT_ISSUER_FAILURE,

        # Network / Transport Timeouts
        "network_timeout": FailureCategory.NETWORK_TIMEOUT,
        "gateway_timeout": FailureCategory.NETWORK_TIMEOUT,
        "timeout": FailureCategory.NETWORK_TIMEOUT,
        "504": FailureCategory.NETWORK_TIMEOUT,

        # Mandate Lifecycle & Status Errors
        "mandate_inactive": FailureCategory.MANDATE_REVOKED,
        "mandate_cancelled": FailureCategory.MANDATE_REVOKED,
        "mandate_revoked": FailureCategory.MANDATE_REVOKED,
        "mandate_expired": FailureCategory.MANDATE_REVOKED,
        "customer_declined": FailureCategory.MANDATE_REVOKED,

        # Authentication / Customer Friction
        "authentication_failed": FailureCategory.AUTH_FRICTION,
        "otp_failed": FailureCategory.AUTH_FRICTION,
        "customer_dropoff": FailureCategory.AUTH_FRICTION,
        "user_auth_timeout": FailureCategory.AUTH_FRICTION,

        # Unrecoverable & Terminal Errors
        "exceeded_limit": FailureCategory.TERMINAL_UNRECOVERABLE,
        "limit_exceeded": FailureCategory.TERMINAL_UNRECOVERABLE,
        "fraud_blocked": FailureCategory.TERMINAL_UNRECOVERABLE,
        "stolen_card": FailureCategory.TERMINAL_UNRECOVERABLE,
        "account_closed": FailureCategory.TERMINAL_UNRECOVERABLE,
    }

    # Deterministic mapping for whether a failure category is inherently retryable
    _RETRYABLE_CATEGORIES = {
        FailureCategory.LIQUIDITY_FAILURE,
        FailureCategory.TRANSIENT_ISSUER_FAILURE,
        FailureCategory.NETWORK_TIMEOUT,
        FailureCategory.AUTH_FRICTION,
        FailureCategory.RAIL_DEGRADATION,
    }

    @classmethod
    def normalize(
        cls,
        raw_error_code: Optional[str],
        raw_error_message: Optional[str] = None,
        provenance: str = "PROVIDER",
    ) -> NormalizedFailure:
        """
        Normalizes a raw error code. If the code is missing or unmapped,
        it fails safely into UNKNOWN_FAILURE rather than guessing.
        """
        if not raw_error_code or not raw_error_code.strip():
            return NormalizedFailure(
                raw_error_code="UNSPECIFIED_ERROR",
                raw_error_message=raw_error_message or "No provider error code provided.",
                category=FailureCategory.UNKNOWN_FAILURE,
                is_retryable_by_nature=False,
                provenance=provenance,
            )

        clean_code = raw_error_code.strip().lower()

        category = cls._EXACT_CODE_MAPPING.get(clean_code, FailureCategory.UNKNOWN_FAILURE)
        is_retryable = category in cls._RETRYABLE_CATEGORIES

        return NormalizedFailure(
            raw_error_code=raw_error_code,
            raw_error_message=raw_error_message,
            category=category,
            is_retryable_by_nature=is_retryable,
            provenance=provenance,
        )
