from pydantic import BaseModel, Field, ConfigDict


class PolicyConfig(BaseModel):
    """
    Deterministic configuration parameters for the Policy Guardian.
    Values can be customized per merchant without code modifications.
    
    All monetary thresholds are represented in integer paisa (₹1 = 100 paisa).
    """
    model_config = ConfigDict(frozen=True)

    # Merchant Business Risk Rules (MERCHANT_POLICY)
    max_retry_attempts: int = Field(
        default=3,
        ge=1,
        description="Maximum automated debit retry attempts allowed per billing cycle (MERCHANT_POLICY).",
    )
    retry_cooldown_seconds: int = Field(
        default=86400,
        ge=0,
        description="Minimum cooldown period in seconds (default: 24h = 86,400s) between automated debit retries (MERCHANT_POLICY).",
    )
    max_notifications: int = Field(
        default=2,
        ge=0,
        description="Maximum customer top-up notifications/nudges permitted per recovery case (MERCHANT_POLICY).",
    )
    high_value_threshold_in_paisa: int = Field(
        default=2500000,
        gt=0,
        description="Threshold in paisa (₹25,000) above which repeated failures require human escalation (MERCHANT_POLICY).",
    )
    high_value_requires_escalation_on_repeat: bool = Field(
        default=True,
        description="Whether high-value subscriptions must escalate to human ops on repeat failures (MERCHANT_POLICY).",
    )

    # Simulation / Operational Parameters (SIMULATION_POLICY)
    authorization_validity_seconds: int = Field(
        default=3600,
        ge=60,
        description="TTL in seconds for an issued PolicyAuthorization record before expiration (SIMULATION_POLICY).",
    )
