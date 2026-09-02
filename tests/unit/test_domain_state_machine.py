import pytest
from datetime import datetime, timezone
from domain.states.recovery_state import (
    RecoveryState,
    RecoveryAction,
    RecoveryStateMachine,
    InvalidStateTransitionError,
)
from domain.models.recovery_case import RecoveryCase


def test_state_machine_valid_happy_path():
    """Verify standard happy-path recovery transition cycle."""
    case = RecoveryCase(
        id="case_101",
        subscription_id="sub_101",
        customer_id="cust_101",
        initial_attempt_id="att_101",
        revenue_at_risk_in_paisa=499900,
        status=RecoveryState.PAYMENT_FAILED,
    )

    # PAYMENT_FAILED -> RECOVERY_ELIGIBLE
    case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE

    # RECOVERY_ELIGIBLE -> RECOVERY_SCHEDULED (WAIT_AND_RETRY)
    case.transition_to(RecoveryState.RECOVERY_SCHEDULED)
    assert case.status == RecoveryState.RECOVERY_SCHEDULED

    # RECOVERY_SCHEDULED -> RECOVERY_ATTEMPTED (Requires Authorization)
    case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)
    assert case.status == RecoveryState.RECOVERY_ATTEMPTED

    # RECOVERY_ATTEMPTED -> RECOVERED (Terminal Success)
    case.mark_recovered(amount_in_paisa=499900)
    assert case.status == RecoveryState.RECOVERED
    assert case.recovered_amount_in_paisa == 499900
    assert case.closed_at is not None


def test_transition_to_recovery_attempted_fails_without_authorization():
    """Invariant: System cannot attempt a recovery debit without explicit PolicyAuthorization."""
    case = RecoveryCase(
        id="case_102",
        subscription_id="sub_102",
        customer_id="cust_102",
        initial_attempt_id="att_102",
        revenue_at_risk_in_paisa=199900,
        status=RecoveryState.RECOVERY_ELIGIBLE,
    )

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=False)

    assert "requires valid PolicyAuthorization" in str(exc_info.value)
    assert case.status == RecoveryState.RECOVERY_ELIGIBLE


def test_terminal_state_protection_recovered():
    """Invariant: Once RECOVERED, state cannot be mutated to active recovery states."""
    case = RecoveryCase(
        id="case_103",
        subscription_id="sub_103",
        customer_id="cust_103",
        initial_attempt_id="att_103",
        revenue_at_risk_in_paisa=299900,
        status=RecoveryState.RECOVERY_ATTEMPTED,
    )
    case.mark_recovered(amount_in_paisa=299900)
    assert case.status == RecoveryState.RECOVERED

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        case.transition_to(RecoveryState.RECOVERY_ATTEMPTED, has_authorization=True)

    assert "Cannot transition out of terminal state" in str(exc_info.value)


def test_terminal_state_protection_stopped():
    """Invariant: Once STOPPED, state cannot be mutated."""
    case = RecoveryCase(
        id="case_104",
        subscription_id="sub_104",
        customer_id="cust_104",
        initial_attempt_id="att_104",
        revenue_at_risk_in_paisa=299900,
        status=RecoveryState.PAYMENT_FAILED,
    )
    case.transition_to(RecoveryState.STOPPED)
    assert case.status == RecoveryState.STOPPED

    with pytest.raises(InvalidStateTransitionError) as exc_info:
        case.transition_to(RecoveryState.RECOVERY_ELIGIBLE)

    assert "Cannot transition out of terminal state" in str(exc_info.value)


def test_illegal_arbitrary_transition():
    """Verify arbitrary jumps (e.g. PAYMENT_FAILED directly to RECOVERED) are blocked."""
    case = RecoveryCase(
        id="case_105",
        subscription_id="sub_105",
        customer_id="cust_105",
        initial_attempt_id="att_105",
        revenue_at_risk_in_paisa=499900,
        status=RecoveryState.PAYMENT_FAILED,
    )

    with pytest.raises(InvalidStateTransitionError):
        case.transition_to(RecoveryState.RECOVERED)
