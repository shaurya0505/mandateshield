import pytest
from domain.models.payment_attempt import FailureCategory
from services.ingestion.failure_normalizer import FailureNormalizer, NormalizedFailure


def test_known_provider_error_mappings():
    """Verify exact canonical mappings for standard provider error codes."""
    # Liquidity
    norm = FailureNormalizer.normalize("insufficient_funds", "Account balance low")
    assert norm.category == FailureCategory.LIQUIDITY_FAILURE
    assert norm.is_retryable_by_nature is True
    assert norm.raw_error_code == "insufficient_funds"

    # Transient Bank Glitch
    norm = FailureNormalizer.normalize("bank_technical_error", "Bank 503 error")
    assert norm.category == FailureCategory.TRANSIENT_ISSUER_FAILURE
    assert norm.is_retryable_by_nature is True

    # Issuer Down
    norm = FailureNormalizer.normalize("issuer_down", "SBI network down")
    assert norm.category == FailureCategory.TRANSIENT_ISSUER_FAILURE
    assert norm.is_retryable_by_nature is True

    # Network Timeout
    norm = FailureNormalizer.normalize("gateway_timeout", "Rail timeout")
    assert norm.category == FailureCategory.NETWORK_TIMEOUT
    assert norm.is_retryable_by_nature is True

    # Mandate Inactive / Revoked
    norm = FailureNormalizer.normalize("mandate_inactive", "Mandate cancelled by user")
    assert norm.category == FailureCategory.MANDATE_REVOKED
    assert norm.is_retryable_by_nature is False

    # Exceeded Limit (Terminal)
    norm = FailureNormalizer.normalize("exceeded_limit", "Amount exceeds max limit")
    assert norm.category == FailureCategory.TERMINAL_UNRECOVERABLE
    assert norm.is_retryable_by_nature is False

    # Auth Friction
    norm = FailureNormalizer.normalize("authentication_failed", "OTP expired")
    assert norm.category == FailureCategory.AUTH_FRICTION
    assert norm.is_retryable_by_nature is True


def test_unknown_and_unmapped_provider_errors_fail_safely():
    """Invariant: Unrecognized or missing error codes must fail-safe into UNKNOWN_FAILURE."""
    # Unknown string code
    norm = FailureNormalizer.normalize("custom_bank_weird_code_999", "Unexpected error")
    assert norm.category == FailureCategory.UNKNOWN_FAILURE
    assert norm.is_retryable_by_nature is False
    assert norm.raw_error_code == "custom_bank_weird_code_999"

    # None / Empty string code
    norm_none = FailureNormalizer.normalize(None)
    assert norm_none.category == FailureCategory.UNKNOWN_FAILURE
    assert norm_none.is_retryable_by_nature is False

    norm_empty = FailureNormalizer.normalize("   ")
    assert norm_empty.category == FailureCategory.UNKNOWN_FAILURE
    assert norm_empty.is_retryable_by_nature is False


def test_normalization_audit_provenance():
    """Verify that provenance and raw fields are retained for audit trail."""
    norm = FailureNormalizer.normalize(
        raw_error_code="insufficient_funds",
        raw_error_message="Debit refused",
        provenance="RAZORPAY_TEST_MODE",
    )
    assert norm.provenance == "RAZORPAY_TEST_MODE"
    assert norm.raw_error_code == "insufficient_funds"
    assert norm.raw_error_message == "Debit refused"
    assert norm.normalized_at is not None
