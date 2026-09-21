"""Purpose: PRISMA counts, agreement/recall statistics against human labels, and ranked reading order from a decisions CSV."""

from __future__ import annotations

import csv
import os
from collections import Counter
from typing import Any

from .decision import EXCLUDE, INCLUDE, MAYBE
from .stats import Confusion, cohens_kappa, confusion, wilson_interval, work_saved_over_sampling

HUMAN_INCLUDE = {"include", "included", "yes", "y", "1", "true", "in"}
HUMAN_EXCLUDE = {"exclude", "excluded", "no", "n", "0", "false", "out"}


def prisma_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts a PRISMA flow diagram needs at the screening step, with exclusions broken down by first reason."""
    labels = Counter(row["decision"] for row in rows)
    reasons = Counter(row["reason"] for row in rows if row["decision"] == EXCLUDE)
    return {
        "screened": len(rows),
        "included": labels.get(INCLUDE, 0),
        "maybe": labels.get(MAYBE, 0),
        "excluded": labels.get(EXCLUDE, 0),
        "excluded_by_reason": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def format_prisma(counts: dict[str, Any]) -> str:
    lines = [
        f"Records screened (title/abstract): {counts['screened']}",
        f"Excluded: {counts['excluded']}",
    ]
    for reason, n in counts["excluded_by_reason"].items():
        lines.append(f"  {reason}: {n}")
    lines.append(f"Maybe (needs a human decision): {counts['maybe']}")
    lines.append(f"Included for full-text review: {counts['included']}")
    return "\n".join(lines)


def read_human_labels(path: str | os.PathLike[str]) -> tuple[dict[str, bool], int]:
    """`id,decision` CSV from human screeners; returns include flags and how many rows had another label."""
    labels: dict[str, bool] = {}
    ignored = 0
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "id" not in reader.fieldnames or "decision" not in reader.fieldnames:
            raise ValueError(f"{path}: expected columns id,decision")
        for row in reader:
            value = (row.get("decision") or "").strip().lower()
            if value in HUMAN_INCLUDE:
                labels[row["id"]] = True
            elif value in HUMAN_EXCLUDE:
                labels[row["id"]] = False
            else:
                ignored += 1
    return labels, ignored


def _interval(successes: int, n: int) -> dict[str, Any]:
    ci = wilson_interval(successes, n)
    return {
        "value": None if n == 0 else successes / n,
        "n": n,
        "wilson_95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
    }


def agreement_report(
    rows: list[dict[str, Any]],
    human: dict[str, bool],
    *,
    maybe_as: str = INCLUDE,
    recall_target: float = 0.95,
) -> dict[str, Any]:
    """Compare tool buckets with human include/exclude on the ids both have.

    `maybe` counts as include by default because a maybe goes to a human anyway: for recall, what matters is
    whether a relevant record survives the automatic step. WSS@95 ranks by `inclusion_score`; records that
    were never judged (no abstract) rank last, which is the honest position for a prioritizer.
    """
    if maybe_as not in (INCLUDE, EXCLUDE):
        raise ValueError("maybe_as must be 'include' or 'exclude'")
    joined = [row for row in rows if row["id"] in human]
    predicted = [row["decision"] == INCLUDE or (row["decision"] == MAYBE and maybe_as == INCLUDE) for row in joined]
    truth = [human[row["id"]] for row in joined]
    matrix: Confusion = confusion(predicted, truth)
    tool_labels = ["include" if p else "exclude" for p in predicted]
    human_labels = ["include" if t else "exclude" for t in truth]
    kappa = cohens_kappa(tool_labels, human_labels)
    scores = [row.get("inclusion_score") if row.get("inclusion_score") is not None else -1.0 for row in joined]
    wss = work_saved_over_sampling(scores, truth, recall_target)
    return {
        "records_compared": len(joined),
        "records_without_human_label": len(rows) - len(joined),
        "human_labels_without_decision": len(set(human) - {row["id"] for row in rows}),
        "maybe_counted_as": maybe_as,
        "maybe_count": sum(1 for row in joined if row["decision"] == MAYBE),
        "confusion": {"tp": matrix.tp, "fp": matrix.fp, "fn": matrix.fn, "tn": matrix.tn},
        "sensitivity_recall": _interval(matrix.tp, matrix.tp + matrix.fn),
        "specificity": _interval(matrix.tn, matrix.tn + matrix.fp),
        "precision": _interval(matrix.tp, matrix.tp + matrix.fp),
        "percent_agreement": _interval(matrix.tp + matrix.tn, matrix.n),
        "cohens_kappa": None if kappa is None else round(kappa, 4),
        "wss": {
            "recall_target": recall_target,
            "human_includes": wss.positives,
            "records_to_read": wss.screened,
            "wss": None if wss.wss is None else round(wss.wss, 4),
        },
    }


def _fmt(metric: dict[str, Any]) -> str:
    if metric["value"] is None:
        return "n/a (no cases)"
    lo, hi = metric["wilson_95"]
    return f"{metric['value']:.3f} (95% Wilson {lo:.3f}-{hi:.3f}, n={metric['n']})"


def format_agreement(report: dict[str, Any]) -> str:
    c = report["confusion"]
    lines = [
        f"Records compared: {report['records_compared']} "
        f"(no human label: {report['records_without_human_label']}, "
        f"human label without decision: {report['human_labels_without_decision']})",
        f"Tool 'maybe' counted as {report['maybe_counted_as']} ({report['maybe_count']} records)",
        f"TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}",
        f"Sensitivity (recall): {_fmt(report['sensitivity_recall'])}",
        f"Specificity: {_fmt(report['specificity'])}",
        f"Precision: {_fmt(report['precision'])}",
        f"Percent agreement: {_fmt(report['percent_agreement'])}",
    ]
    kappa = report["cohens_kappa"]
    lines.append("Cohen's kappa: " + ("n/a" if kappa is None else f"{kappa:.3f}"))
    wss = report["wss"]
    if wss["wss"] is None:
        lines.append("WSS@95: n/a (no human includes)")
    else:
        lines.append(
            f"WSS@{int(wss['recall_target'] * 100)}: {wss['wss']:.3f} "
            f"(read {wss['records_to_read']} of {report['records_compared']} ranked records to reach "
            f"{int(wss['recall_target'] * 100)}% of {wss['human_includes']} human includes)"
        )
    return "\n".join(lines)


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reading order for humans: highest inclusion score first; unjudged records (no score) last, then by id."""

    def key(row: dict[str, Any]) -> tuple[int, float, str]:
        score = row.get("inclusion_score")
        return (0, -score, row["id"]) if score is not None else (1, 0.0, row["id"])

    ranked = sorted(rows, key=key)
    for position, row in enumerate(ranked, start=1):
        row["rank"] = position
    return ranked
