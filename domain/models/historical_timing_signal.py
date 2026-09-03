from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class HistoricalPaymentTimingSignal(BaseModel):
    """
    Deterministic historical payment timing signal derived strictly from
    empirically observed successful recurring payment timestamps.
    
    NOTE: This represents observed payment settlement timing patterns.
    It does NOT assume, infer, or claim knowledge of external customer salary/income dates.
    """
    model_config = ConfigDict(frozen=True)

    has_timing_signal: bool
    window_start_day: Optional[int] = Field(default=None, ge=1, le=31)
    window_end_day: Optional[int] = Field(default=None, ge=1, le=31)
    sample_size: int = Field(default=0, ge=0)
    matching_observations: int = Field(default=0, ge=0)
    support_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    in_current_window: bool = False
    days_until_next_window: Optional[int] = Field(default=None, ge=0)
    explanation: str
