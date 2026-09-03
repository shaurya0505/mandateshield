from enum import Enum


class RecoveryPriorityLevel(str, Enum):
    """Deterministic priority classification for triage and scheduling."""
    CRITICAL = "CRITICAL"    # High-value / High-likelihood recovery required immediately
    HIGH = "HIGH"            # Standard high-value or highly recoverable failure
    MEDIUM = "MEDIUM"        # Standard priority recovery
    LOW = "LOW"              # Low value or decaying recovery likelihood
    NEGLIGIBLE = "NEGLIGIBLE"# Unrecoverable (e.g. revoked mandate, stolen instrument)
