from abc import ABC, abstractmethod
from domain.models.recovery_context import RecoveryContext
from domain.models.strategy_proposal import StrategyProposal


class StrategyPlanner(ABC):
    """
    Abstract interface for recovery strategy planning components.
    Accepts an immutable RecoveryContext and returns a structured StrategyProposal.
    """

    @abstractmethod
    def propose_strategy(self, context: RecoveryContext) -> StrategyProposal:
        """
        Evaluates the recovery context and proposes an optimal recovery action.
        """
        pass
