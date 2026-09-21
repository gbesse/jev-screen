"""Purpose: Code-owned include / exclude / maybe rule applied to per-criterion probabilities, with the first failing reason."""

from __future__ import annotations

from dataclasses import dataclass

from .criteria import Criteria

INCLUDE = "include"
EXCLUDE = "exclude"
MAYBE = "maybe"
REASON_ALL_MET = "all_criteria_met"
REASON_NO_ABSTRACT = "no_abstract"
REASON_EMPTY = "empty_record"


@dataclass(frozen=True)
class Decision:
    label: str
    reason: str
    inclusion_score: float | None


def inclusion_score(criteria: Criteria, probabilities: dict[str, float]) -> float:
    """Weakest-link score for ranking: the smallest of inclusion p and (1 - exclusion p).

    A record is only as eligible as its least satisfied criterion, so the minimum orders reading lists in a
    way that is consistent with the bucket rule (every include scores >= include_min, every exclude <= exclude_max).
    """
    values = [probabilities[c.id] for c in criteria.inclusion]
    values += [1.0 - probabilities[c.id] for c in criteria.exclusion]
    return min(values)


def decide(criteria: Criteria, probabilities: dict[str, float]) -> Decision:
    """Apply the thresholds in criteria order and remember the first criterion that fails hard.

    Include: every inclusion p >= include_min and every exclusion p <= exclude_max.
    Exclude: any inclusion p <= exclude_max or any exclusion p >= include_min (reason = first such criterion).
    Maybe: everything else (reason = first criterion inside the uncertain band).
    Probabilities are independent nouls, so no arithmetic is done on them beyond these comparisons.
    """
    missing = [c.id for c in criteria.all if c.id not in probabilities]
    if missing:
        raise KeyError(f"missing probabilities for criteria: {', '.join(missing)}")
    first_fail = None
    first_uncertain = None
    for criterion in criteria.inclusion:
        p = probabilities[criterion.id]
        if p <= criteria.exclude_max:
            first_fail = first_fail or f"inclusion:{criterion.id}"
        elif p < criteria.include_min:
            first_uncertain = first_uncertain or f"uncertain:{criterion.id}"
    for criterion in criteria.exclusion:
        p = probabilities[criterion.id]
        if p >= criteria.include_min:
            first_fail = first_fail or f"exclusion:{criterion.id}"
        elif p > criteria.exclude_max:
            first_uncertain = first_uncertain or f"uncertain:{criterion.id}"
    score = inclusion_score(criteria, probabilities)
    if first_fail:
        return Decision(EXCLUDE, first_fail, score)
    if first_uncertain:
        return Decision(MAYBE, first_uncertain, score)
    return Decision(INCLUDE, REASON_ALL_MET, score)


def decide_unjudged(criteria: Criteria, reason: str) -> Decision:
    """Records Jev never saw (no abstract, empty record) follow `unknown_policy`; default routes them to a human."""
    label = EXCLUDE if criteria.unknown_policy == "exclude" else MAYBE
    return Decision(label, reason, None)
