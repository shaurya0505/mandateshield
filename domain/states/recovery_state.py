from enum import Enum
from typing import Set


class RecoveryState(str, Enum):
    """
    Explicit lifecycle states for subscription payments and recovery cases.
    Distinguished cleanly from third-party payment gateway states.
    """
    ACTIVE = "ACTIVE"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    RECOVERY_ELIGIBLE = "RECOVERY_ELIGIBLE"
    RECOVERY_SCHEDULED = "RECOVERY_SCHEDULED"
    RECOVERY_ATTEMPTED = "RECOVERY_ATTEMPTED"
    RECOVERED = "RECOVERED"
    ESCALATED = "ESCALATED"
    HALTED = "HALTED"
    STOPPED = "STOPPED"


class RecoveryAction(str, Enum):
    """
    Canonical, bounded recovery action space.
    The AI strategy planner and policy engine can ONLY select from this set.
    """
    WAIT_AND_RETRY = "WAIT_AND_RETRY"             # Schedule re-attempt during historical payment window
    RETRY_NOW = "RETRY_NOW"                       # Immediate re-attempt on same rail (transient glitch)
    SWITCH_PAYMENT_PATH = "SWITCH_PAYMENT_PATH"   # Charge an alternative verified mandate/payment method
    GENERATE_PAYMENT_LINK = "GENERATE_PAYMENT_LINK"# Issue a standard Razorpay Payment Link / invoice
    SEND_RECOVERY_NUDGE = "SEND_RECOVERY_NUDGE"   # Dispatch customer communication via SMS/WhatsApp/Email
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"       # Route to high-touch concierge / merchant ops
    STOP_RECOVERY = "STOP_RECOVERY"               # Terminal halt (mandate cancelled, fraud, persistent refusal)


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""
    def __init__(self, current_state: RecoveryState, target_state: RecoveryState, reason: str = ""):
        message = f"Illegal transition from {current_state.value} to {target_state.value}."
        if reason:
            message += f" Reason: {reason}"
        super().__init__(message)
        self.current_state = current_state
        self.target_state = target_state
        self.reason = reason


class RecoveryStateMachine:
    """
    Deterministic Finite State Machine governing recovery case lifecycles.
    Enforces strict transition guards, fail-closed validation, and terminal state protection.
    """

    VALID_TRANSITIONS: dict[RecoveryState, Set[RecoveryState]] = {
        RecoveryState.ACTIVE: {
            RecoveryState.PAYMENT_PENDING,
            RecoveryState.STOPPED,
        },
        RecoveryState.PAYMENT_PENDING: {
            RecoveryState.RECOVERED,       # Payment succeeded organically
            RecoveryState.PAYMENT_FAILED,  # Payment attempt failed
        },
        RecoveryState.PAYMENT_FAILED: {
            RecoveryState.RECOVERY_ELIGIBLE,  # Ingestion & Normalization passed
            RecoveryState.STOPPED,            # Unrecoverable (e.g. mandate revoked)
            RecoveryState.HALTED,             # Immediate policy block
        },
        RecoveryState.RECOVERY_ELIGIBLE: {
            RecoveryState.RECOVERY_SCHEDULED, # Strategy approved: WAIT_AND_RETRY / NUDGE
            RecoveryState.RECOVERY_ATTEMPTED, # Strategy approved: RETRY_NOW / SWITCH_PATH
            RecoveryState.ESCALATED,          # High value / Ambiguity / Manual intervention required
            RecoveryState.HALTED,             # Policy limit reached / Cooldown active
            RecoveryState.STOPPED,            # Terminal unrecoverable decision
        },
        RecoveryState.RECOVERY_SCHEDULED: {
            RecoveryState.RECOVERY_ATTEMPTED, # Scheduled window arrived & execution authorized
            RecoveryState.ESCALATED,          # Manual intervention triggered while waiting
            RecoveryState.STOPPED,            # Subscription cancelled during wait window
        },
        RecoveryState.RECOVERY_ATTEMPTED: {
            RecoveryState.RECOVERED,          # Recovery attempt succeeded
            RecoveryState.PAYMENT_FAILED,     # Recovery attempt failed (initiates next cycle evaluation)
            RecoveryState.ESCALATED,          # Gateway error / indeterminate result requiring review
        },
        RecoveryState.ESCALATED: {
            RecoveryState.RECOVERY_ATTEMPTED, # Human operator authorized manual retry/action
            RecoveryState.RECOVERY_SCHEDULED, # Human operator rescheduled action
            RecoveryState.STOPPED,            # Human operator marked case as terminal/written-off
            RecoveryState.RECOVERED,          # Manual out-of-band payment confirmed
        },
        RecoveryState.HALTED: {
            RecoveryState.RECOVERY_ELIGIBLE,  # Cooldown elapsed or condition cleared
            RecoveryState.ESCALATED,          # Escalated after remaining halted
            RecoveryState.STOPPED,            # Final write-off
        },
        # Terminal states have no outbound transitions
        RecoveryState.RECOVERED: set(),
        RecoveryState.STOPPED: set(),
    }

    TERMINAL_STATES: Set[RecoveryState] = {
        RecoveryState.RECOVERED,
        RecoveryState.STOPPED,
    }

    @classmethod
    def is_terminal(cls, state: RecoveryState) -> bool:
        return state in cls.TERMINAL_STATES

    @classmethod
    def can_transition(cls, from_state: RecoveryState, to_state: RecoveryState) -> bool:
        return to_state in cls.VALID_TRANSITIONS.get(from_state, set())

    @classmethod
    def validate_transition(cls, from_state: RecoveryState, to_state: RecoveryState, has_authorization: bool = False) -> None:
        """
        Validates whether a transition is permitted according to state machine invariants.
        Raises InvalidStateTransitionError if illegal.
        """
        if cls.is_terminal(from_state):
            raise InvalidStateTransitionError(
                from_state, to_state, "Cannot transition out of terminal state."
            )

        allowed_targets = cls.VALID_TRANSITIONS.get(from_state, set())
        if to_state not in allowed_targets:
            raise InvalidStateTransitionError(
                from_state, to_state, f"Valid targets from {from_state.value} are: {[s.value for s in allowed_targets]}"
            )

        # Invariant: Transitioning to RECOVERY_ATTEMPTED requires explicit policy authorization
        if to_state == RecoveryState.RECOVERY_ATTEMPTED and not has_authorization:
            raise InvalidStateTransitionError(
                from_state,
                to_state,
                "Transition to RECOVERY_ATTEMPTED requires valid PolicyAuthorization record."
            )
