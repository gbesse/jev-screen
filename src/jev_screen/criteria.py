"""Purpose: Load and validate the criteria JSON and turn it into the fan-out noul questions and the Jev state."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .records import Record

_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
DEFAULT_INCLUDE_MIN = 0.7
DEFAULT_EXCLUDE_MAX = 0.3
UNKNOWN_POLICIES = ("maybe", "exclude")
# One request holds one noul per criterion; beyond this the state/question budget and accuracy both suffer.
MAX_CRITERIA = 40


class CriteriaError(ValueError):
    """The criteria file is malformed; screening must not start with an ambiguous rule set."""


@dataclass(frozen=True)
class Criterion:
    id: str
    kind: str  # "inclusion" | "exclusion"
    statement: str
    true_description: str = ""
    false_description: str = ""

    def question(self) -> dict[str, Any]:
        """A direct statement works best with Jev's literal reading; criteria descriptions sharpen the boundary."""
        question: dict[str, Any] = {"type": "noul", "instructions": self.statement}
        if self.true_description or self.false_description:
            question["criteria"] = {
                "true": self.true_description or f"The statement holds: {self.statement}",
                "false": self.false_description or f"The statement does not hold: {self.statement}",
            }
        return question


@dataclass(frozen=True)
class Criteria:
    review: str
    inclusion: tuple[Criterion, ...]
    exclusion: tuple[Criterion, ...]
    include_min: float = DEFAULT_INCLUDE_MIN
    exclude_max: float = DEFAULT_EXCLUDE_MAX
    unknown_policy: str = "maybe"

    @property
    def all(self) -> tuple[Criterion, ...]:
        return self.inclusion + self.exclusion

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.all]

    def questions(self) -> dict[str, Any]:
        """Every criterion becomes an independent noul in one request (fan-out on the same small state)."""
        return {c.id: c.question() for c in self.all}


def _text(value: Any, where: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise CriteriaError(f"{where} must be a non-empty string")
    return value.strip()


def _criterion(data: Any, kind: str, index: int) -> Criterion:
    where = f"{kind}[{index}]"
    if not isinstance(data, dict):
        raise CriteriaError(f"{where} must be an object")
    cid = _text(data.get("id"), f"{where}.id")
    if not _ID.match(cid):
        raise CriteriaError(f"{where}.id {cid!r} must match [a-z][a-z0-9_]* (it becomes a CSV column)")
    return Criterion(
        id=cid,
        kind=kind,
        statement=_text(data.get("statement"), f"{where}.statement"),
        true_description=_text(data.get("true"), f"{where}.true", required=False),
        false_description=_text(data.get("false"), f"{where}.false", required=False),
    )


def parse_criteria(data: Any) -> Criteria:
    if not isinstance(data, dict):
        raise CriteriaError("criteria must be a JSON object")
    inclusion_raw = data.get("inclusion")
    if not isinstance(inclusion_raw, list) or not inclusion_raw:
        raise CriteriaError("'inclusion' must be a non-empty list")
    exclusion_raw = data.get("exclusion", [])
    if not isinstance(exclusion_raw, list):
        raise CriteriaError("'exclusion' must be a list")
    inclusion = tuple(_criterion(c, "inclusion", i) for i, c in enumerate(inclusion_raw))
    exclusion = tuple(_criterion(c, "exclusion", i) for i, c in enumerate(exclusion_raw))
    ids = [c.id for c in inclusion + exclusion]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise CriteriaError(f"duplicate criterion id(s): {', '.join(duplicates)}")
    if len(ids) > MAX_CRITERIA:
        raise CriteriaError(f"at most {MAX_CRITERIA} criteria per review (got {len(ids)})")
    thresholds = data.get("thresholds", {})
    if not isinstance(thresholds, dict):
        raise CriteriaError("'thresholds' must be an object")
    include_min = thresholds.get("include_min", DEFAULT_INCLUDE_MIN)
    exclude_max = thresholds.get("exclude_max", DEFAULT_EXCLUDE_MAX)
    for name, value in (("include_min", include_min), ("exclude_max", exclude_max)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 < value < 1.0:
            raise CriteriaError(f"thresholds.{name} must be a number strictly between 0 and 1")
    if exclude_max >= include_min:
        raise CriteriaError("thresholds.exclude_max must be lower than thresholds.include_min")
    policy = data.get("unknown_policy", "maybe")
    if policy not in UNKNOWN_POLICIES:
        raise CriteriaError(f"unknown_policy must be one of {UNKNOWN_POLICIES}")
    return Criteria(
        review=_text(data.get("review", "untitled review"), "review"),
        inclusion=inclusion,
        exclusion=exclusion,
        include_min=float(include_min),
        exclude_max=float(exclude_max),
        unknown_policy=policy,
    )


def load_criteria(path: str | os.PathLike[str]) -> Criteria:
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError as err:
            raise CriteriaError(f"{path}: invalid JSON ({err})") from err
    return parse_criteria(data)


def build_state(record: Record) -> dict[str, str]:
    """State is title + abstract only: year, authors and journal are irrelevant to eligibility and dilute accuracy."""
    state = {"title": record.title.strip()}
    if record.has_abstract():
        state["abstract"] = record.abstract.strip()
    return state
