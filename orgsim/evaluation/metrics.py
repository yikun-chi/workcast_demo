"""Shared scoring functions. Every instance's evaluation uses these so numbers are comparable."""
from __future__ import annotations

import math
from collections import Counter
from typing import Iterable, Sequence

import numpy as np


def accuracy(pred: Sequence, truth: Sequence) -> float:
    n = len(truth)
    return sum(1 for p, t in zip(pred, truth) if p == t) / n if n else float("nan")


def log_loss(probs: Sequence[dict], truth: Sequence, eps: float = 1e-6) -> float:
    vals = [-math.log(max(eps, p.get(t, 0.0))) for p, t in zip(probs, truth)]
    return float(np.mean(vals)) if vals else float("nan")


def jensen_shannon(a: Counter | dict, b: Counter | dict) -> float:
    keys = set(a) | set(b)
    pa = np.array([a.get(k, 0) for k in keys], dtype=float); pb = np.array([b.get(k, 0) for k in keys], dtype=float)
    if pa.sum() == 0 or pb.sum() == 0:
        return float("nan")
    pa /= pa.sum(); pb /= pb.sum(); m = (pa + pb) / 2
    def kl(p, q):
        mask = p > 0
        return float(np.sum(p[mask] * np.log2(p[mask] / q[mask])))
    return 0.5 * kl(pa, m) + 0.5 * kl(pb, m)


def mae(pred: Iterable[float], truth: Iterable[float]) -> float:
    p = np.asarray(list(pred), dtype=float); t = np.asarray(list(truth), dtype=float)
    return float(np.mean(np.abs(p - t))) if len(t) else float("nan")


def pp_error(pred_rate: float, true_rate: float) -> float:
    """Percentage-point error between two proportions given in percent."""
    return float(pred_rate - true_rate)


def interval(samples: Iterable[float], level: float = 0.9) -> tuple[float, float]:
    s = np.asarray(list(samples), dtype=float)
    if len(s) == 0:
        return (float("nan"), float("nan"))
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return float(np.quantile(s, lo)), float(np.quantile(s, hi))


def coverage(samples: Iterable[float], truth: float, level: float = 0.9) -> bool:
    lo, hi = interval(samples, level)
    return bool(lo <= truth <= hi)


def rank_correlation(a: Sequence[float], b: Sequence[float]) -> float:
    from scipy.stats import spearmanr
    if len(a) < 3:
        return float("nan")
    return float(spearmanr(a, b).statistic)
