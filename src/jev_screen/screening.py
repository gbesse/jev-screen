"""Purpose: Screen records against criteria: one fan-out request per record, cache, resume, bounded concurrency."""

from __future__ import annotations

import csv
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .cache import ResultCache
from .client import JevResult, estimate_cost_usd, request_key
from .criteria import Criteria, build_state
from .decision import REASON_EMPTY, REASON_NO_ABSTRACT, Decision, decide, decide_unjudged
from .records import Record

FIXED_COLUMNS = ["id", "title", "decision", "reason", "inclusion_score"]
TRAILING_COLUMNS = ["input_tokens", "cached", "model", "request_key"]


@dataclass(frozen=True)
class ScreenResult:
    record: Record
    decision: Decision
    probabilities: dict[str, float]
    input_tokens: int
    cached: bool
    model: str
    request_key: str

    @property
    def cost_usd(self) -> float:
        return 0.0 if self.cached else estimate_cost_usd(self.input_tokens)


def result_columns(criteria: Criteria) -> list[str]:
    return FIXED_COLUMNS + [f"p_{cid}" for cid in criteria.ids] + TRAILING_COLUMNS


def result_row(result: ScreenResult, criteria: Criteria) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": result.record.id,
        "title": result.record.title,
        "decision": result.decision.label,
        "reason": result.decision.reason,
        "inclusion_score": "" if result.decision.inclusion_score is None else f"{result.decision.inclusion_score:.4f}",
        "input_tokens": result.input_tokens,
        "cached": "1" if result.cached else "0",
        "model": result.model,
        "request_key": result.request_key,
    }
    for cid in criteria.ids:
        p = result.probabilities.get(cid)
        row[f"p_{cid}"] = "" if p is None else f"{p:.4f}"
    return row


def read_decisions(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read a decisions CSV back; probability and score columns become floats (or None when blank)."""
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "decision", "reason"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected columns {sorted(required)}")
        for raw in reader:
            row: dict[str, Any] = dict(raw)
            for key, value in raw.items():
                if key == "inclusion_score" or key.startswith("p_"):
                    row[key] = float(value) if value not in (None, "") else None
            rows.append(row)
    return rows


def completed_ids(path: str | os.PathLike[str], criteria: Criteria) -> set[str]:
    """Ids already in the output file; the header must match so resumed rows stay aligned with the criteria."""
    file = Path(path)
    if not file.exists() or file.stat().st_size == 0:
        return set()
    with file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != result_columns(criteria):
            raise ValueError(
                f"{path} has columns that do not match the criteria; use a new --out file or the same criteria"
            )
        return {row["id"] for row in reader if row.get("id")}


def screen_one(
    record: Record,
    criteria: Criteria,
    provider: Any,
    *,
    cache: ResultCache | None = None,
    title_only: bool = False,
) -> ScreenResult:
    """Judge one record. Records without text are never sent: the model cannot judge what it cannot read."""
    state = build_state(record)
    questions = criteria.questions()
    model = getattr(provider, "model", "")
    key = request_key(model, state, questions)
    if not state["title"] and "abstract" not in state:
        return ScreenResult(record, decide_unjudged(criteria, REASON_EMPTY), {}, 0, False, model, key)
    if "abstract" not in state and not title_only:
        return ScreenResult(record, decide_unjudged(criteria, REASON_NO_ABSTRACT), {}, 0, False, model, key)
    result: JevResult | None = cache.get(key) if cache is not None else None
    if result is None:
        result = provider.ask(state, questions)
        if cache is not None:
            cache.put(key, result)
    probabilities = {cid: float(result.answers[cid]["noul"]) for cid in criteria.ids}
    return ScreenResult(
        record=record,
        decision=decide(criteria, probabilities),
        probabilities=probabilities,
        input_tokens=result.input_tokens,
        cached=result.cached,
        model=result.model,
        request_key=key,
    )


def screen_records(
    records: Iterable[Record],
    criteria: Criteria,
    provider: Any,
    *,
    cache: ResultCache | None = None,
    title_only: bool = False,
    concurrency: int = 8,
    skip_ids: Iterable[str] = (),
    on_result: Callable[[ScreenResult], None] | None = None,
) -> list[ScreenResult]:
    """Screen many records with bounded threads; results and `on_result` callbacks follow the input order.

    Completed results are buffered until every earlier record is done, so the decisions file is deterministic
    and diff-friendly while rows are still flushed during the run (resume via `skip_ids` after an interruption
    loses at most the buffered tail, which the cache still holds). Any provider error cancels the remaining
    work and propagates.
    """
    skip = set(skip_ids)
    todo = [r for r in records if r.id not in skip]
    results: dict[str, ScreenResult] = {}
    workers = max(1, int(concurrency))
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(screen_one, record, criteria, provider, cache=cache, title_only=title_only): record
            for record in todo
        }
        try:
            for future in as_completed(futures):
                result = future.result()
                results[result.record.id] = result
                while next_index < len(todo) and todo[next_index].id in results:
                    if on_result is not None:
                        on_result(results[todo[next_index].id])
                    next_index += 1
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    return [results[r.id] for r in todo]
