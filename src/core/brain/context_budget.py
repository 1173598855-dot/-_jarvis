from __future__ import annotations

from collections.abc import Callable

from core.contracts.context_budget import (
    ContextBudgetSnapshot,
    ContextWatermarkChanged,
)
from core.contracts.run_state import ContextLevel

RuntimeReader = Callable[[], tuple[int, int] | None]


def _is_token_count(value: object, *, positive: bool = False) -> bool:
    minimum = 1 if positive else 0
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


class FallbackContextBudgetProvider:
    def __init__(
        self,
        total_tokens: int,
        estimate: Callable[[], int],
        runtime_reader: RuntimeReader | None = None,
    ) -> None:
        self._total_tokens = total_tokens
        self._estimate = estimate
        self._runtime_reader = runtime_reader

    def snapshot(self) -> ContextBudgetSnapshot:
        if not _is_token_count(self._total_tokens, positive=True):
            raise ValueError("total_tokens must be a positive integer")

        runtime = self._read_runtime()
        if runtime is not None:
            used_tokens, total_tokens = runtime
            return ContextBudgetSnapshot(used_tokens, total_tokens, "runtime")

        used_tokens = self._estimate()
        if not _is_token_count(used_tokens):
            raise ValueError("used_tokens estimate must be a non-negative integer")
        return ContextBudgetSnapshot(
            min(used_tokens, self._total_tokens),
            self._total_tokens,
            "estimate",
        )

    def _read_runtime(self) -> tuple[int, int] | None:
        if self._runtime_reader is None:
            return None
        try:
            reading = self._runtime_reader()
        except Exception:
            return None
        if not isinstance(reading, tuple) or len(reading) != 2:
            return None
        used_tokens, total_tokens = reading
        if not _is_token_count(total_tokens, positive=True):
            return None
        if not _is_token_count(used_tokens) or used_tokens > total_tokens:
            return None
        return used_tokens, total_tokens


class ContextBudgetMonitor:
    def __init__(
        self,
        *,
        amber: float = 0.65,
        orange: float = 0.80,
        red: float = 0.90,
    ) -> None:
        thresholds = (amber, orange, red)
        if (
            any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in thresholds)
            or not 0 < amber < orange < red <= 1
        ):
            raise ValueError("threshold values must satisfy 0 < amber < orange < red <= 1")
        self._amber = float(amber)
        self._orange = float(orange)
        self._red = float(red)
        self._current = ContextLevel.GREEN

    def level_for(self, snapshot: ContextBudgetSnapshot) -> ContextLevel:
        if not isinstance(snapshot, ContextBudgetSnapshot):
            raise ValueError("snapshot must be a ContextBudgetSnapshot")
        ratio = snapshot.usage_ratio
        if ratio >= self._red:
            return ContextLevel.RED
        if ratio >= self._orange:
            return ContextLevel.ORANGE
        if ratio >= self._amber:
            return ContextLevel.AMBER
        return ContextLevel.GREEN

    def observe(
        self,
        snapshot: ContextBudgetSnapshot,
    ) -> ContextWatermarkChanged | None:
        current = self.level_for(snapshot)
        if current is self._current:
            return None
        previous = self._current
        self._current = current
        return ContextWatermarkChanged(previous, current, snapshot)
