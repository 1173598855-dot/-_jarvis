from dataclasses import dataclass
from typing import Protocol

from core.contracts.run_state import ContextLevel


@dataclass(frozen=True, slots=True)
class ContextBudgetSnapshot:
    used_tokens: int
    total_tokens: int
    source: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.total_tokens, int)
            or isinstance(self.total_tokens, bool)
            or self.total_tokens <= 0
        ):
            raise ValueError("total_tokens must be a positive integer")
        if (
            not isinstance(self.used_tokens, int)
            or isinstance(self.used_tokens, bool)
            or self.used_tokens < 0
            or self.used_tokens > self.total_tokens
        ):
            raise ValueError("used_tokens must be between zero and total_tokens")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be a non-empty string")

    @property
    def usage_ratio(self) -> float:
        return self.used_tokens / self.total_tokens


class ContextBudgetProvider(Protocol):
    def snapshot(self) -> ContextBudgetSnapshot: ...


@dataclass(frozen=True, slots=True)
class ContextWatermarkChanged:
    previous: ContextLevel
    current: ContextLevel
    snapshot: ContextBudgetSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.previous, ContextLevel):
            raise ValueError("previous must be a ContextLevel")
        if not isinstance(self.current, ContextLevel):
            raise ValueError("current must be a ContextLevel")
        if not isinstance(self.snapshot, ContextBudgetSnapshot):
            raise ValueError("snapshot must be a ContextBudgetSnapshot")
