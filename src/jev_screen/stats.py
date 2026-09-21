"""Purpose: Stdlib statistics for screening evaluation: Wilson intervals, Cohen's kappa, recall/specificity, WSS@95."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

Z_95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval; preferred over the normal approximation because screening samples are small."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("need 0 <= successes <= n")
    if n == 0:
        return None
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, n: int) -> float | None:
    return None if n == 0 else successes / n


def cohens_kappa(rater_a: Sequence[str], rater_b: Sequence[str]) -> float | None:
    """Chance-corrected agreement between two label sequences of equal length over the same items."""
    if len(rater_a) != len(rater_b):
        raise ValueError("label sequences must have the same length")
    n = len(rater_a)
    if n == 0:
        return None
    observed = sum(1 for a, b in zip(rater_a, rater_b) if a == b) / n
    count_a, count_b = Counter(rater_a), Counter(rater_b)
    expected = sum(count_a[c] * count_b[c] for c in set(count_a) | set(count_b)) / (n * n)
    if expected == 1.0:
        # Both raters use a single label: kappa is undefined; report perfect agreement or none.
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


@dataclass(frozen=True)
class Confusion:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def sensitivity(self) -> float | None:
        """Recall of the positive (include) class: the metric that matters for screening."""
        return proportion(self.tp, self.tp + self.fn)

    @property
    def specificity(self) -> float | None:
        return proportion(self.tn, self.tn + self.fp)

    @property
    def precision(self) -> float | None:
        return proportion(self.tp, self.tp + self.fp)

    @property
    def accuracy(self) -> float | None:
        return proportion(self.tp + self.tn, self.n)


def confusion(predicted: Iterable[bool], truth: Iterable[bool]) -> Confusion:
    tp = fp = fn = tn = 0
    for pred, true in zip(predicted, truth, strict=True):
        if pred and true:
            tp += 1
        elif pred and not true:
            fp += 1
        elif not pred and true:
            fn += 1
        else:
            tn += 1
    return Confusion(tp, fp, fn, tn)


@dataclass(frozen=True)
class WorkSaved:
    recall_target: float
    n: int
    positives: int
    screened: int  # how many top-ranked records a human must read to reach the recall target
    wss: float | None

    @property
    def screened_fraction(self) -> float | None:
        return proportion(self.screened, self.n)


def work_saved_over_sampling(scores: Sequence[float], truth: Sequence[bool], recall_target: float = 0.95) -> WorkSaved:
    """WSS@R = (TN + FN) / N - (1 - R) after ranking by score.

    Records are read from the highest score down until `recall_target` of the human includes are found.
    Ties are broken pessimistically (non-includes first) so equal scores never inflate the saving.
    """
    if len(scores) != len(truth):
        raise ValueError("scores and truth must have the same length")
    n = len(scores)
    positives = sum(1 for t in truth if t)
    if n == 0 or positives == 0:
        return WorkSaved(recall_target, n, positives, 0, None)
    needed = math.ceil(recall_target * positives - 1e-9)
    order = sorted(range(n), key=lambda i: (-scores[i], truth[i]))
    found = 0
    screened = n
    for rank, index in enumerate(order, start=1):
        if truth[index]:
            found += 1
            if found >= needed:
                screened = rank
                break
    wss = (n - screened) / n - (1.0 - recall_target)
    return WorkSaved(recall_target, n, positives, screened, wss)
