"""Conventional baselines every process-type instance is compared against."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable, Sequence


class MarkovNextActivity:
    """k-th order Markov next-activity model fitted on training traces (sequences of activity ids)."""

    def __init__(self, order: int = 1, end_token: str = "<END>") -> None:
        self.order, self.end = order, end_token
        self.counts: dict[tuple, Counter] = defaultdict(Counter)

    def fit(self, traces: Iterable[Sequence[str]]) -> "MarkovNextActivity":
        for tr in traces:
            seq = list(tr) + [self.end]
            for i in range(len(seq) - 1):
                ctx = tuple(seq[max(0, i - self.order + 1): i + 1])
                self.counts[ctx][seq[i + 1]] += 1
        return self

    def probs(self, prefix: Sequence[str]) -> dict[str, float]:
        for k in range(self.order, 0, -1):
            ctx = tuple(prefix[-k:]) if len(prefix) >= k else None
            if ctx and ctx in self.counts:
                c = self.counts[ctx]; tot = sum(c.values())
                return {a: n / tot for a, n in c.items()}
        return {}

    def predict(self, prefix: Sequence[str]) -> str | None:
        p = self.probs(prefix)
        return max(p, key=p.get) if p else None
