"""Purpose: Screen records against criteria: one fan-out request per record, cache, resume, bounded concurrency."""

from __future__ import annotations

import csv
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .cache import ResultCache
from .client import (
    JevResult,
    estimate_cost_usd,
    request_key,
    validate_response,
    JevError,
)
from .criteria import Criteria, build_state
from .decision import (
    REASON_EMPTY,
    REASON_NO_ABSTRACT,
    Decision,
    decide,
    decide_unjudged,
)
from .records import Record, check_unique_ids
from .provenance import (
    ProtocolError,
    ScreeningContext,
    record_fingerprint,
    row_fingerprint,
)

FIXED_COLUMNS = ["id", "title", "decision", "reason", "inclusion_score"]
TRAILING_COLUMNS = [
    "input_tokens",
    "cached",
    "model",
    "request_key",
    "protocol_sha256",
    "record_sha256",
    "row_sha256",
]


@dataclass(frozen=True)
class ScreenResult:
    record: Record
    decision: Decision
    probabilities: dict[str, float]
    input_tokens: int
    cached: bool
    model: str
    request_key: str
    protocol_sha256: str = ""
    record_sha256: str = ""

    @property
    def cost_usd(self) -> float:
        return 0.0 if self.cached else estimate_cost_usd(self.input_tokens)


def result_columns(criteria: Criteria) -> list[str]:
    return FIXED_COLUMNS + [f"p_{cid}" for cid in criteria.ids] + TRAILING_COLUMNS


def result_row(result: ScreenResult, criteria: Criteria) -> dict[str, Any]:
    if not result.protocol_sha256 or result.record_sha256 != record_fingerprint(
        result.record
    ):
        raise ProtocolError("record")
    row: dict[str, Any] = {
        "id": result.record.id,
        "title": result.record.title,
        "decision": result.decision.label,
        "reason": result.decision.reason,
        "inclusion_score": ""
        if result.decision.inclusion_score is None
        else f"{result.decision.inclusion_score:.4f}",
        "input_tokens": result.input_tokens,
        "cached": "1" if result.cached else "0",
        "model": result.model,
        "request_key": result.request_key,
        "protocol_sha256": result.protocol_sha256,
        "record_sha256": result.record_sha256,
    }
    for cid in criteria.ids:
        p = result.probabilities.get(cid)
        row[f"p_{cid}"] = "" if p is None else f"{p:.4f}"
    row["row_sha256"] = row_fingerprint(row)
    return row


def read_decisions(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read a decisions CSV back; probability and score columns become floats (or None when blank)."""
    rows: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "decision", "reason"}
        error = "CSV de décisions invalide / Invalid decisions CSV / CSV de decisiones no válido"
        if reader.fieldnames is None or not required.issubset(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(error)
        seen = set()
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()) or not raw["id"].strip() or raw["id"] in seen or raw["decision"] not in {"include", "exclude", "maybe"}:
                raise ValueError(error)
            seen.add(raw["id"])
            row: dict[str, Any] = dict(raw)
            for key, value in raw.items():
                if key == "inclusion_score" or key.startswith("p_"):
                    try:
                        probability = float(value) if value != "" else None
                    except ValueError:
                        raise ValueError(error) from None
                    if probability is not None and (not math.isfinite(probability) or not 0 <= probability <= 1):
                        raise ValueError(error)
                    row[key] = probability
            rows.append(row)
    return rows


def completed_ids(
    path: str | os.PathLike[str],
    criteria: Criteria,
    *,
    records: Iterable[Record] | None = None,
    provider: Any = None,
    title_only: bool = False,
) -> set[str]:
    """Validate every existing row before skipping it. Legacy rows cannot prove their context."""
    file = Path(path)
    if not file.exists() or file.stat().st_size == 0:
        return set()
    with file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != result_columns(criteria):
            raise ProtocolError("header")
        if records is None or provider is None:
            raise ProtocolError("context")
        current = list(records)
        check_unique_ids(current)
        by_id = {r.id: record_fingerprint(r) for r in current}
        expected = ScreeningContext.build(
            criteria, provider, title_only=title_only
        ).protocol_sha256
        done: set[str] = set()
        for row in reader:
            # Extra cells use the None key, missing cells use None values. Refuse an interrupted tail.
            if (
                None in row
                or any(v is None for v in row.values())
                or not row.get("id")
                or row["id"] in done
            ):
                raise ProtocolError("row")
            if row["row_sha256"] != row_fingerprint(row):
                raise ProtocolError("row")
            if row["protocol_sha256"] != expected:
                raise ProtocolError("protocol")
            if row["record_sha256"] != by_id.get(row["id"]):
                raise ProtocolError("record")
            done.add(row["id"])
        return done


def screen_one(
    record: Record,
    criteria: Criteria,
    provider: Any,
    *,
    cache: ResultCache | None = None,
    title_only: bool = False,
    _context: ScreeningContext | None = None,
) -> ScreenResult:
    """Judge one record. Records without text are never sent: the model cannot judge what it cannot read."""
    context = _context or ScreeningContext.build(
        criteria, provider, title_only=title_only
    )
    record_sha256 = record_fingerprint(record)
    state = build_state(record)
    questions = criteria.questions()
    model = getattr(provider, "model", "")
    key = request_key(model, state, questions)
    if not state["title"] and "abstract" not in state:
        return ScreenResult(
            record,
            decide_unjudged(criteria, REASON_EMPTY),
            {},
            0,
            False,
            model,
            key,
            context.protocol_sha256,
            record_sha256,
        )
    if "abstract" not in state and not title_only:
        return ScreenResult(
            record,
            decide_unjudged(criteria, REASON_NO_ABSTRACT),
            {},
            0,
            False,
            model,
            key,
            context.protocol_sha256,
            record_sha256,
        )
    cache_key = context.cache_key(key)
    try:
        result: JevResult | None = cache.get(cache_key) if cache is not None else None
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ProtocolError("cache") from None
    if result is None:
        result = provider.ask(state, questions)
    try:
        validate_response(
            {"model": result.model, "answers": result.answers, "usage": result.usage},
            questions,
            model,
        )
        if set(result.answers) != set(questions):
            raise ValueError("question set")
        for value in result.usage.values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("token usage")
    except (JevError, ValueError, KeyError, TypeError, AttributeError):
        raise ProtocolError(
            "cache" if result is not None and result.cached else "answer"
        ) from None
    if cache is not None and not result.cached:
        cache.put(cache_key, result)
    probabilities = {cid: float(result.answers[cid]["noul"]) for cid in criteria.ids}
    return ScreenResult(
        record=record,
        decision=decide(criteria, probabilities),
        probabilities=probabilities,
        input_tokens=result.input_tokens,
        cached=result.cached,
        model=result.model,
        request_key=key,
        protocol_sha256=context.protocol_sha256,
        record_sha256=record_sha256,
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
    context = ScreeningContext.build(criteria, provider, title_only=title_only)
    records = list(records)
    check_unique_ids(records)
    skip = set(skip_ids)
    todo = [r for r in records if r.id not in skip]
    results: dict[str, ScreenResult] = {}
    workers = max(1, int(concurrency))
    next_index = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                screen_one,
                record,
                criteria,
                provider,
                cache=cache,
                title_only=title_only,
                _context=context,
            ): record
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
